from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from attendance import views

router = DefaultRouter()
for route, view in [('users', views.UserViewSet), ('departments', views.DepartmentViewSet), ('courses', views.CourseViewSet),
                    ('sections', views.SectionViewSet), ('schedules', views.ScheduleViewSet), ('students', views.StudentViewSet),
                    ('memberships', views.MembershipViewSet), ('sessions', views.SessionViewSet),
                    ('jobs', views.JobViewSet), ('audit', views.AuditViewSet)]:
    router.register(route, view, basename=route)
urlpatterns = [path('admin/', admin.site.urls), path('api/', include(router.urls)),
               path('api/auth/csrf/', views.CSRFView.as_view()), path('api/auth/login/', views.LoginView.as_view()),
               path('api/auth/me/', views.MeView.as_view()), path('api/enroll/', views.PublicEnrollmentView.as_view()),
               path('api/classifier/', views.ClassifierView.as_view()),
               path('api/classifier/status/', views.ClassifierStatusView.as_view())]
