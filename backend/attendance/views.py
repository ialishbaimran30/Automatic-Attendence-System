import io
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from rest_framework import viewsets
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import *
from .serializers import *
from .permissions import IsAdminRole, IsStaffRole, authorize_section, sections_for, is_admin
from . import services
from .reports import grid, workbook
from .enrollment import prepare_samples, save_samples, consume_link, CONSENT_VERSION, EnrollmentUnavailable
from .errors import failure_response
from recognition.engine import validate_image, RecognitionRejected
from recognition.storage import write_private, delete_private, invalidate_classifier

def integer_id(data, key): return drf_serializers.IntegerField(min_value=1).run_validation(data.get(key))
def uuid_id(data, key): return drf_serializers.UUIDField().run_validation(data.get(key))
def reason_text(data): return drf_serializers.CharField(max_length=1000, trim_whitespace=True).run_validation(data.get('reason'))

class CSRFView(APIView):
    permission_classes = [AllowAny]
    def get(self, request): return Response({'csrfToken': get_token(request)})

@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        user = authenticate(request, username=request.data.get('username'), password=request.data.get('password'))
        if not user or not user.is_active or user.role not in ('teacher', 'admin'):
            return Response({'detail': 'Invalid staff credentials.'}, status=400)
        login(request, user)
        services.audit('auth.login', user)
        return Response(UserSerializer(user).data)

class MeView(APIView):
    def get(self, request): return Response(UserSerializer(request.user).data)
    def delete(self, request):
        services.audit('auth.logout', request.user)
        logout(request)
        return Response(status=204)

class AdminViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminRole]
    lookup_value_regex = r'\d+'
    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save()
        services.audit('admin.created', self.request.user, model=instance.__class__.__name__, id=instance.pk)
    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        services.audit('admin.updated', self.request.user, model=instance.__class__.__name__, id=instance.pk)
    @transaction.atomic
    def perform_destroy(self, instance):
        from django.db.models.deletion import ProtectedError
        label, pk = instance.__class__.__name__, instance.pk
        try:
            instance.delete()
            if isinstance(instance, Student): invalidate_classifier()
        except ProtectedError: raise ValidationError('This record has protected history. Deactivate users/students or preserve referenced data.')
        services.audit('admin.deleted', self.request.user, model=label, id=pk)

class UserViewSet(AdminViewSet):
    queryset = User.objects.all().order_by('id')
    serializer_class = UserSerializer
class DepartmentViewSet(AdminViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
class CourseViewSet(AdminViewSet):
    queryset = Course.objects.all()
    serializer_class = CourseSerializer
class ScheduleViewSet(AdminViewSet):
    queryset = Schedule.objects.all()
    serializer_class = ScheduleSerializer
class MembershipViewSet(AdminViewSet):
    queryset = Membership.objects.all()
    serializer_class = MembershipSerializer

class SectionViewSet(AdminViewSet):
    serializer_class = SectionSerializer
    def get_permissions(self):
        return [IsAdminRole()] if self.action in ('create', 'update', 'partial_update', 'destroy') else [IsStaffRole()]
    def get_queryset(self): return sections_for(self.request.user).select_related('course').prefetch_related('schedules', 'teachers')
    @action(detail=True, methods=['post'], url_path='configure-class')
    def configure_class(self, request, pk=None):
        section = self.get_object()
        config = ClassConfigurationSerializer(data=request.data)
        config.is_valid(raise_exception=True)
        schedule = services.configure_class(request.user, section, **config.validated_data)
        return Response(ScheduleSerializer(schedule).data, status=201)
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        section = self.get_object()
        schedule = get_object_or_404(Schedule, pk=integer_id(request.data, 'schedule'), section=section)
        try: session = services.start_session(request.user, section, schedule)
        except IntegrityError: raise ValidationError('A session already exists for this section or scheduled occurrence.')
        return Response(SessionSerializer(session).data, status=201)
    @action(detail=True, methods=['get'])
    def grid(self, request, pk=None): return Response(grid(self.get_object(), request.query_params))
    @action(detail=True, methods=['get'])
    def export(self, request, pk=None):
        section = self.get_object()
        data = grid(section, request.query_params)
        stream = io.BytesIO()
        workbook(data).save(stream)
        services.audit('attendance.exported', request.user, section=section, filters=dict(request.query_params))
        response = HttpResponse(stream.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="section-{section.pk}-attendance.xlsx"'
        return response

class StudentViewSet(AdminViewSet):
    serializer_class = StudentSerializer
    def get_permissions(self):
        return [IsAdminRole()] if self.action in ('create', 'update', 'partial_update', 'destroy', 'purge_biometrics') else [IsStaffRole()]
    def get_queryset(self):
        qs = Student.objects.all() if is_admin(self.request.user) else Student.objects.filter(
            Q(sections__in=sections_for(self.request.user)) | Q(sessionroster__session__section__in=sections_for(self.request.user))).distinct()
        if self.request.query_params.get('section'):
            section = get_object_or_404(sections_for(self.request.user), pk=integer_id(self.request.query_params, 'section'))
            qs = qs.filter(sections=section)
        return qs.order_by('registration_number')
    @action(detail=True, methods=['get'])
    def percentages(self, request, pk=None):
        student = self.get_object()
        # Include historical roster snapshots as well as current memberships, still scoped to teacher sections.
        accessible = sections_for(request.user).filter(Q(students=student) | Q(attendance_sessions__roster__student=student)).distinct()
        results = []
        for section in accessible:
            data = grid(section, request.query_params)
            result = next((s for s in data['students'] if s['student'] == student.pk), None)
            if result: results.append({'section': section.pk, 'threshold': data['threshold'], **result})
        return Response(results)
    @action(detail=True, methods=['post'], url_path='enrollment-link')
    def enrollment_link(self, request, pk=None):
        student = self.get_object()
        if not student.active: raise ValidationError('Student is inactive.')
        token = secrets.token_urlsafe(32)
        link = EnrollmentLink.objects.create(student=student, token_hash=services.token_hash(token), issued_by=request.user,
            expires_at=timezone.now() + timedelta(minutes=30))
        services.audit('enrollment.link_issued', request.user, student_id=student.pk)
        return Response({'url': f'{settings.FRONTEND_ORIGIN}/enroll#{token}', 'expires_at': link.expires_at})
    @action(detail=True, methods=['post'], url_path='bulk-enroll')
    def bulk_enroll(self, request, pk=None):
        student = self.get_object()
        if not student.active or request.data.get('consent') != 'true': raise ValidationError('Active student and recorded explicit consent required.')
        try:
            prepared = prepare_samples(request.FILES.getlist('photos'))
            with transaction.atomic():
                student = Student.objects.select_for_update().get(pk=student.pk)
                save_samples(student, prepared, uuid.uuid4())
                student.consent_at, student.consent_version = timezone.now(), CONSENT_VERSION
                student.save(update_fields=['consent_at', 'consent_version'])
                services.audit('enrollment.bulk_saved', request.user, student_id=student.pk, count=len(prepared), consent_version=CONSENT_VERSION)
        except ValidationError:
            services.audit('enrollment.rejected', request.user, student_id=student.pk)
            raise
        except EnrollmentUnavailable as exc:
            services.audit('enrollment.error', request.user, student_id=student.pk, code=exc.payload['code'], error_id=exc.payload['error_id'])
            return Response(exc.payload, status=503)
        except Exception as exc:
            response = failure_response(exc, 'enrollment_storage')
            services.audit('enrollment.error', request.user, student_id=student.pk, code=response.data['code'], error_id=response.data['error_id'])
            return response
        return Response({'saved': len(prepared), 'detail': 'Encrypted enrollment saved for reuse across enrolled sections. Attendance unchanged.',
                         'training': 'Collect three independent capture events per student and ask an administrator to train on stored embeddings.'}, status=201)
    @action(detail=True, methods=['post'], url_path='purge-biometrics')
    @transaction.atomic
    def purge_biometrics(self, request, pk=None):
        student = self.get_object()
        reason = str(request.data.get('reason', '')).strip()
        if not reason: raise ValidationError('Deletion reason required.')
        student = Student.objects.select_for_update().get(pk=student.pk)
        count, _ = student.biometrics.all().delete()
        invalidate_classifier()
        student.consent_at, student.consent_version = None, ''
        student.save(update_fields=['consent_at', 'consent_version'])
        student.enrollmentlink_set.filter(used_at__isnull=True).update(expires_at=timezone.now())
        services.audit('biometrics.deleted', request.user, student_id=student.pk, count=count, reason=reason)
        return Response({'deleted': count})

class PublicEnrollmentView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    def post(self, request):
        try: consume_link(str(request.data.get('token', '')), request.FILES.getlist('photos'), request.data.get('consent'))
        except ValidationError: raise
        except EnrollmentUnavailable as exc:
            services.audit('enrollment.error', code=exc.payload['code'], error_id=exc.payload['error_id'])
            return Response(exc.payload, status=503)
        except Exception as exc:
            response = failure_response(exc, 'enrollment_storage')
            services.audit('enrollment.error', code=response.data['code'], error_id=response.data['error_id'])
            return response
        return Response({'detail': 'Enrollment saved. This does not record attendance.'}, status=201)

class SessionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = SessionSerializer
    lookup_value_regex = r'[0-9a-fA-F-]{36}'
    def get_queryset(self):
        qs = AttendanceSession.objects.filter(section__in=sections_for(self.request.user)).prefetch_related('roster', 'records').order_by('-scheduled_start')
        if self.request.query_params.get('section'): qs = qs.filter(section_id=integer_id(self.request.query_params, 'section'))
        return qs
    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        self.get_object()
        return Response(SessionSerializer(services.close_session(request.user, pk)).data)
    @action(detail=True, methods=['post'])
    def manual(self, request, pk=None):
        self.get_object()
        record = services.manual_record(request.user, pk, integer_id(request.data, 'student'), reason_text(request.data))
        return Response(RecordSerializer(record).data, status=201)
    @action(detail=True, methods=['post'])
    def correct(self, request, pk=None):
        self.get_object()
        record = services.correct_record(request.user, pk, integer_id(request.data, 'student'), request.data.get('status'), reason_text(request.data))
        return Response(RecordSerializer(record).data)
    @action(detail=True, methods=['post'], url_path='capture-grant')
    def capture_grant(self, request, pk=None):
        self.get_object()
        token, expires = services.issue_capture(request.user, pk)
        return Response({'token': token, 'expires_at': expires})
    @action(detail=True, methods=['post'])
    def capture(self, request, pk=None):
        self.get_object()
        photo = request.FILES.get('frame')
        if not photo: raise ValidationError('Raw JPEG/PNG frame required.')
        data = photo.read(5 * 1024 * 1024 + 1)
        try: validate_image(data)
        except RecognitionRejected as exc: raise ValidationError(str(exc))
        path = write_private(data)
        try: job = services.create_job(request.user, pk, str(request.data.get('token', '')), path)
        except Exception:
            delete_private(path)
            raise
        from .tasks import recognize
        try: recognize.delay(str(job.pk))
        except Exception:
            delete_private(path)
            job.status, job.reason, job.frame_path = 'error', 'queue_unavailable', ''
            job.save()
            services.audit('recognition.error', request.user, job.session, job_id=str(job.pk), reason='queue_unavailable')
        job.refresh_from_db()
        return Response(JobSerializer(job).data, status=202)
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        self.get_object()
        return Response(RecordSerializer(services.confirm_job(request.user, pk, uuid_id(request.data, 'job'))).data, status=201)

class JobViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = JobSerializer
    lookup_value_regex = r'[0-9a-fA-F-]{36}'
    def get_queryset(self):
        qs = RecognitionJob.objects.filter(session__section__in=sections_for(self.request.user))
        if not is_admin(self.request.user): qs = qs.filter(requested_by=self.request.user)
        return qs.order_by('-captured_at')

class AuditViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditSerializer
    def get_queryset(self):
        qs = AuditLog.objects.all() if is_admin(self.request.user) else AuditLog.objects.filter(section__in=sections_for(self.request.user))
        if self.request.query_params.get('section'): qs = qs.filter(section_id=integer_id(self.request.query_params, 'section'))
        return qs

class ClassifierView(APIView):
    permission_classes = [IsAdminRole]
    def get(self, request):
        from recognition.classifier import load
        try: return Response(load()['report'])
        except RecognitionRejected as exc: return Response({'detail': str(exc)}, status=409)
        except Exception as exc: return failure_response(exc, 'classifier_load')
    def post(self, request):
        from recognition.classifier import train, training_status
        services.audit('classifier.training_started', request.user)
        try: report = train()
        except ValueError as exc:
            services.audit('classifier.training_rejected', request.user, reason='insufficient_or_invalid_training_data')
            return Response({'detail': 'Insufficient or invalid training data: ' + str(exc), 'code': 'insufficient_training_data',
                             'action': 'Collect at least three independent capture events for each enrolled student, with at least two students.',
                             'training_data': training_status()}, status=409)
        except Exception as exc:
            response = failure_response(exc, 'classifier_training')
            services.audit('classifier.training_error', request.user, code=response.data['code'], error_id=response.data['error_id'])
            return response
        services.audit('classifier.trained', request.user, train_samples=report['train_samples'], heldout_samples=report['heldout_samples'], accuracy=report['accuracy'])
        return Response(report, status=201)

class ClassifierStatusView(APIView):
    permission_classes = [IsAdminRole]
    def get(self, request):
        from recognition.classifier import training_status, load
        data = training_status()
        try:
            report = load()['report']
            data['classifier'] = 'current'
            data['trained_at'] = report['trained_at']
        except RecognitionRejected as exc: data['classifier'] = str(exc)
        except Exception as exc: return failure_response(exc, 'classifier_load')
        return Response(data)
