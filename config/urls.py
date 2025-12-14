from django.contrib import admin
from django.urls import path, include
from tracker import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('profile/', views.profile, name='profile'),
    # Django auth URLs
    path('accounts/', include('django.contrib.auth.urls')),
    # Cognito Hosted UI endpoints
    path('auth/login/', views.cognito_login, name='cognito_login'),
    path('auth/callback/', views.cognito_callback, name='cognito_callback'),
    path('auth/logout/', views.cognito_logout, name='cognito_logout'),
    # Custom logout that clears Cognito tokens (overrides Django's default logout)
    path('accounts/logout/', views.cognito_logout, name='logout'),
    # Include tracker URLs (this includes: signup, login, index, add, save_planting, delete, edit, update)
    path('', include('tracker.urls')),
]