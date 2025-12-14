from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

class SignUpForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        label='Username',
        widget=forms.TextInput(attrs={'placeholder':'Username', 'autocomplete': 'username'})
    )
    email = forms.EmailField(
        required=True,
        label='Email',
        widget=forms.EmailInput(attrs={'placeholder':'Email', 'autocomplete': 'email'})
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={'placeholder':'Password', 'autocomplete': 'new-password'}),
        min_length=8,
        required=True,
    )
    password2 = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={'placeholder':'Confirm Password', 'autocomplete': 'new-password'}),
        min_length=8,
        required=True,
    )
    country = forms.CharField(
        max_length=100,
        required=True,
        label='Country',
        widget=forms.TextInput(attrs={'placeholder':'Country', 'autocomplete': 'country-name'})
    )
    
    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise ValidationError("A user with that username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with that email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        if 'password1' in cleaned_data and 'password2' in cleaned_data:
            if cleaned_data['password1'] != cleaned_data['password2']:
                raise ValidationError("Passwords do not match.")
        return cleaned_data