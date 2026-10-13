from rest_framework import serializers
from .models import (User, Department, Course, Section, Schedule, Student, Membership, AttendanceSession,
                     SessionRoster, AttendanceRecord, RecognitionJob, AuditLog)

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=10)
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'role', 'is_active', 'password']
    def validate(self, attrs):
        if not self.instance and not attrs.get('password'): raise serializers.ValidationError('Password is required.')
        if attrs.get('password'):
            from django.contrib.auth.password_validation import validate_password
            validate_password(attrs['password'], self.instance)
        return attrs
    def create(self, validated_data):
        password = validated_data.pop('password')
        return User.objects.create_user(password=password, **validated_data)
    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=['password'])
        return instance

class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ['id', 'name']
class CourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Course
        fields = ['id', 'department', 'code', 'name', 'attendance_threshold', 'grace_minutes', 'match_threshold', 'match_margin']
class ScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Schedule
        fields = ['id', 'section', 'weekday', 'start_time', 'end_time', 'valid_from', 'valid_until', 'grace_minutes']
    def validate(self, attrs):
        def value(key): return attrs.get(key, getattr(self.instance, key, None))
        if value('end_time') <= value('start_time') or value('valid_until') < value('valid_from'):
            raise serializers.ValidationError('Schedule must have increasing times and dates; overnight schedules are unsupported.')
        return attrs
class SectionSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course.code', read_only=True)
    schedules = ScheduleSerializer(many=True, read_only=True)
    effective_threshold = serializers.SerializerMethodField()
    effective_grace_minutes = serializers.SerializerMethodField()
    time_zone = serializers.SerializerMethodField()
    class Meta:
        model = Section
        fields = ['id', 'course', 'course_code', 'name', 'semester', 'teachers', 'schedules', 'attendance_threshold',
                  'effective_threshold', 'effective_grace_minutes', 'time_zone', 'grace_minutes', 'match_threshold', 'match_margin']
    def get_effective_threshold(self, obj): return obj.setting('attendance_threshold')
    def get_effective_grace_minutes(self, obj): return obj.setting('grace_minutes')
    def get_time_zone(self, obj):
        from django.conf import settings
        return settings.TIME_ZONE
    def validate_teachers(self, teachers):
        if any(t.role != 'teacher' or not t.is_active for t in teachers):
            raise serializers.ValidationError('Assign active teachers only.')
        return teachers
class StudentSerializer(serializers.ModelSerializer):
    enrolled_samples = serializers.SerializerMethodField()
    capture_groups = serializers.SerializerMethodField()
    class Meta:
        model = Student
        fields = ['id', 'registration_number', 'name', 'department', 'active', 'consent_at', 'consent_version', 'enrolled_samples', 'capture_groups']
        read_only_fields = ['consent_at', 'consent_version']
    def get_enrolled_samples(self, obj):
        from django.utils import timezone
        return obj.biometrics.filter(expires_at__gt=timezone.now()).count()
    def get_capture_groups(self, obj):
        from django.utils import timezone
        return obj.biometrics.filter(expires_at__gt=timezone.now()).values('capture_group').distinct().count()

class ClassConfigurationSerializer(serializers.Serializer):
    class_date = serializers.DateField()
    start_time = serializers.TimeField()
    duration_minutes = serializers.IntegerField(min_value=1, max_value=480)
    grace_minutes = serializers.IntegerField(min_value=0, max_value=120)
class MembershipSerializer(serializers.ModelSerializer):
    class Meta:
        model = Membership
        fields = ['id', 'student', 'section']
class RosterSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionRoster
        fields = ['student', 'name', 'registration_number']
class RecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = ['id', 'student', 'status', 'timestamp', 'score', 'actor', 'method', 'job']
class SessionSerializer(serializers.ModelSerializer):
    roster = RosterSerializer(many=True, read_only=True)
    records = RecordSerializer(many=True, read_only=True)
    checked_in_count = serializers.SerializerMethodField()
    class Meta:
        model = AttendanceSession
        fields = ['id', 'section', 'schedule', 'scheduled_start', 'scheduled_end', 'started_at', 'closed_at',
                  'started_by', 'grace_minutes', 'roster', 'records', 'checked_in_count']
    def get_checked_in_count(self, obj): return obj.records.filter(status__in=['present', 'late']).count()
class JobSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()
    action = serializers.SerializerMethodField()
    class Meta:
        model = RecognitionJob
        fields = ['id', 'session', 'status', 'proposed_student', 'name', 'score', 'reason', 'action', 'captured_at', 'expires_at', 'confirmed_at']
    def get_name(self, obj):
        row = obj.session.roster.filter(student_id=obj.proposed_student_id).first()
        return row.name if row else None
    def expired(self, obj):
        from django.utils import timezone
        return obj.status in ('queued', 'processing', 'review') and obj.expires_at <= timezone.now()
    def get_status(self, obj): return 'rejected' if self.expired(obj) else obj.status
    def get_reason(self, obj): return 'job_expired' if self.expired(obj) else obj.reason
    def get_action(self, obj):
        from .errors import REJECTIONS, MESSAGES
        code = self.get_reason(obj)
        return REJECTIONS.get(code, MESSAGES.get(code, ('', ''))[1])
class AuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = ['id', 'at', 'actor', 'section', 'session', 'event', 'details']
