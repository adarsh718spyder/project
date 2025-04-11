from datetime import timedelta

def generate_schedule(tasks):
    """
    Sort tasks by priority first (High -> Low), then by start time.
    """
    sorted_tasks = sorted(tasks, key=lambda x: (x['priority'], x['start_time']))
    
    return sorted_tasks

def calculate_total_time(tasks):
    total_seconds = sum(task['duration'] for task in tasks)
    return timedelta(seconds=total_seconds)

def get_free_time_slots(tasks):
    """
    Calculate free time slots between tasks.
    """
    tasks = sorted(tasks, key=lambda x: x['end_time'])
    free_slots = []

    # Assuming a workday from 9:00 AM to 5:00 PM
    work_start = timedelta(hours=9, minutes=0)
    work_end = timedelta(hours=17, minutes=0)

    prev_end_time = work_start

    for task in tasks:
        task_start_time = task['start_time'].time()
        task_end_time = task['end_time'].time()

        # Check if there's a free slot between tasks
        if task_start_time > prev_end_time:
            free_slots.append({
                'start': prev_end_time,
                'end': task_start_time,
                'duration': task_start_time - prev_end_time
            })

        # Update the previous task end time
        prev_end_time = task_end_time

    # Add final free slot if there's any time left after the last task
    if prev_end_time < work_end:
        free_slots.append({
            'start': prev_end_time,
            'end': work_end,
            'duration': work_end - prev_end_time
        })

    return free_slots
