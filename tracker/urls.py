from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('signup/', views.signup, name='signup'),
    path('login/', views.login_view, name='login'),  # Use custom login view that redirects to Cognito
    path('', views.index, name='index'),
    path('add/', views.add_planting_view, name='add_planting'),
    path('save_planting/', views.save_planting, name='save_planting'),
    path('delete/<int:planting_id>/', views.delete_planting, name='delete_planting'),
    path('edit/<int:planting_id>/', views.edit_planting_view, name='edit_planting'),
    path('update/<int:planting_id>/', views.update_planting, name='update_planting'),
    path('api/toggle-notifications/', views.toggle_notifications, name='toggle_notifications'),
    path('api/notification-summaries/', views.get_notification_summaries, name='get_notification_summaries'),
]