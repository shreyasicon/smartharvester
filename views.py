import json
from datetime import date, timedelta
from django.shortcuts import render
from django.http import HttpResponse

# This would be in your Django app's views.py file

# Helper function to load the plant data from the JSON file
def load_plant_data():
    with open('data.json', 'r') as f:
        return json.load(f)

def index(request):
    """
    This view will eventually display the user's saved plantings.
    For now, it's just a placeholder showing how to render the template.
    """
    # In a real app, you would fetch saved_plantings from your database.
    # Here we are just passing dummy data for the template to render.
    context = {
        'plantings': [
            # This data would be calculated and retrieved from a database
        ]
    }
    return render(request, 'index.html', context)

def add_planting_view(request):
    """
    This view displays the form to add a new planting.
    """
    plant_data = load_plant_data()
    plant_names = [plant['name'] for plant in plant_data['plants']]
    context = {
        'plant_names': plant_names
    }
    return render(request, 'edit.html', context)

def save_planting(request):
    """
    This view handles the form submission, calculates the care plan,
    and would save it to a database.
    """
    if request.method == 'POST':
        crop_name = request.POST.get('crop_name')
        planting_date_str = request.POST.get('planting_date')
        planting_date = date.fromisoformat(planting_date_str)

        plant_data = load_plant_data()
        
        # Find the selected plant's care schedule
        schedule_info = None
        for plant in plant_data['plants']:
            if plant['name'] == crop_name:
                schedule_info = plant['care_schedule']
                break
        
        # Calculate the full care plan with actual dates
        calculated_plan = []
        if schedule_info:
            for task in schedule_info:
                due_date = planting_date + timedelta(days=task['days_after_planting'])
                calculated_plan.append({
                    'task': task['task_title'],
                    'due_date': due_date.isoformat()
                })
        
        # In a real app, you would save the following to your database:
        # - user_id
        # - crop_name
        # - planting_date
        # - calculated_plan
        
        print(f"Saving for user: SaiShreyas203")
        print(f"Crop: {crop_name}, Planted on: {planting_date}")
        print("Calculated Plan:")
        print(calculated_plan)

        # After saving, redirect back to the home page
        # from django.shortcuts import redirect
        # return redirect('/')
        
        return HttpResponse(f"<h1>Plan for {crop_name} saved!</h1><pre>{calculated_plan}</pre><a href='/'>Back to Dashboard</a>")

    return HttpResponse("Invalid request method.", status=405)
