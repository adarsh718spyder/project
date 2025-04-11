import os
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file, flash
from datetime import datetime, timedelta, timezone
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
import matplotlib.pyplot as plt
import io
import scheduler
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from fpdf import FPDF
from io import BytesIO
from gcal import get_calendar_service, add_event_to_calendar, save_token_from_flow
from flask import send_file
from fpdf import FPDF
from io import BytesIO


app = Flask(__name__)
app.secret_key = 'your_secret_key'

CLIENT_SECRETS_FILE = "credentials.json"
SCOPES = ['https://www.googleapis.com/auth/calendar']

flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri='http://localhost:5000/oauth2callback'
)

# ---------------- Helper functions ----------------

def serialize_tasks(tasks):
    return [
        {
            'task_name': t['task_name'],
            'start_time': t['start_time'].isoformat(),
            'end_time': t['end_time'].isoformat(),
            'priority': t['priority'],
            'duration': t['duration'],
            'completed': t.get('completed', False),
            'calendar_link': t.get('calendar_link', '')
        } for t in tasks
    ]

def deserialize_tasks(tasks):
    deserialized = []
    for t in tasks:
        start = t['start_time']
        end = t['end_time']
        if isinstance(start, str):
            start = datetime.fromisoformat(start)
        if isinstance(end, str):
            end = datetime.fromisoformat(end)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        deserialized.append({
            'task_name': t['task_name'],
            'start_time': start,
            'end_time': end,
            'priority': t['priority'],
            'duration': t['duration'],
            'completed': t.get('completed', False),
            'calendar_link': t.get('calendar_link', '')
        })
    return deserialized

# ---------------- Routes ----------------

@app.route('/')
def index():
    tasks = deserialize_tasks(session.get('tasks', []))
    total_minutes = sum(t['duration'] for t in tasks) // 60
    completed_tasks = sum(1 for t in tasks if t.get('completed'))
    return render_template('index.html', total_minutes=int(total_minutes), completed_tasks=completed_tasks, tasks=tasks)

@app.route('/add_task', methods=['POST'])
def add_task():
    task_name = request.form['task_name']
    start_time = datetime.strptime(request.form['start_time'], '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
    end_time = datetime.strptime(request.form['end_time'], '%Y-%m-%dT%H:%M').replace(tzinfo=timezone.utc)
    priority = int(request.form['priority'])
    duration = (end_time - start_time).total_seconds()

    new_task = {
        'task_name': task_name,
        'start_time': start_time,
        'end_time': end_time,
        'priority': priority,
        'duration': duration,
        'completed': False,
        'calendar_link': ''
    }

    tasks = deserialize_tasks(session.get('tasks', []))
    tasks.append(new_task)
    session['tasks'] = serialize_tasks(tasks)
    session.modified = True

    return redirect(url_for('index'))

@app.route('/complete_task/<int:index>', methods=['POST'])
def complete_task(index):
    tasks = deserialize_tasks(session.get('tasks', []))
    if 0 <= index < len(tasks):
        tasks[index]['completed'] = True
    session['tasks'] = serialize_tasks(tasks)
    flash("Task marked as completed.", "success")
    return redirect(url_for('index'))

@app.route('/delete_task/<int:index>', methods=['POST'])
def delete_task(index):
    tasks = deserialize_tasks(session.get('tasks', []))
    if 0 <= index < len(tasks):
        tasks.pop(index)
    session['tasks'] = serialize_tasks(tasks)
    flash("Task deleted.", "danger")
    return redirect(url_for('index'))

@app.route('/clear_tasks')
def clear_tasks():
    session.pop('tasks', None)
    flash("All tasks cleared.", "danger")
    return redirect(url_for('index'))

@app.route('/sync_calendar')
def sync_calendar():
    high_priority_only = request.args.get('high_priority', 'false') == 'true'
    tasks = deserialize_tasks(session.get('tasks', []))
    synced = []

    for i, task in enumerate(tasks):
        if high_priority_only and task['priority'] != 1:
            continue

        task_data = {
            'task': task['task_name'],
            'start': task['start_time'].isoformat(),
            'end': task['end_time'].isoformat()
        }
        result = add_event_to_calendar(task_data)
        if isinstance(result, str) and result.startswith("http"):
            session['pending_sync_tasks'] = session.get('tasks', [])
            return redirect(result)
        elif isinstance(result, dict):
            tasks[i]['calendar_link'] = result.get('htmlLink', '')
            synced.append(task['task_name'])

    session['tasks'] = serialize_tasks(tasks)
    flash(f"Synced {len(synced)} task(s) to Google Calendar.", "info")
    return redirect(url_for('index'))

@app.route("/oauth2callback")
def oauth2callback():
    flow = Flow.from_client_secrets_file(
        'credentials.json',
        scopes=['https://www.googleapis.com/auth/calendar'],
        redirect_uri='http://localhost:5000/oauth2callback'
    )
    save_token_from_flow(flow, request.url)



    tasks = deserialize_tasks(session.get('pending_sync_tasks', []))
    for i, task in enumerate(tasks):
        task_data = {
            'task': task['task_name'],
            'start': task['start_time'].isoformat(),
            'end': task['end_time'].isoformat()
        }
        result = add_event_to_calendar(task_data)
        if isinstance(result, dict):
            tasks[i]['calendar_link'] = result.get('htmlLink', '')

    session['tasks'] = serialize_tasks(tasks)
    session.pop('pending_sync_tasks', None)
    flash("Calendar sync complete after authorization.", "success")
    return redirect(url_for('index'))

@app.route('/generate_schedule')
def generate_schedule():
    if 'tasks' not in session:
        return redirect(url_for('index'))

    tasks = deserialize_tasks(session['tasks'])
    sorted_tasks = scheduler.generate_schedule(tasks)
    return render_template('schedule.html', tasks=sorted_tasks)

@app.route('/analytics')
def analytics():
    tasks = deserialize_tasks(session.get('tasks', []))
    
    total_time = scheduler.calculate_total_time(tasks)
    completed = sum(1 for t in tasks if t['completed'])
    missed = len(tasks) - completed

    time_data = {'High': 0, 'Medium': 0, 'Low': 0}
    completion_data = {'Completed': 0, 'Missed': 0}
    line_data = {}  # fix: define it so it's not undefined

    for t in tasks:
        priority = {1: 'High', 2: 'Medium', 3: 'Low'}[t['priority']]
        time_data[priority] += t['duration'] / 60

        if t['completed']:
            completion_data['Completed'] += 1
        else:
            completion_data['Missed'] += 1

        date_key = t['start_time'].date().isoformat()
        line_data[date_key] = line_data.get(date_key, 0) + t['duration'] / 60

    return render_template(
        'analytics.html',
        total_time=total_time,
        completed_tasks=completed,
        missed_tasks=missed,
        time_data=time_data,
        completion_data=completion_data,
        line_data=line_data  # ✅ this fixes the error
    )



@app.route('/download_pdf')
def download_pdf():
    if 'tasks' not in session:
        return redirect(url_for('index'))

    tasks = deserialize_tasks(session['tasks'])
    now = datetime.now(timezone.utc)

    #  Calculate analytics
    completed = sum(1 for task in tasks if task['end_time'] <= now or task.get('completed'))
    missed = len(tasks) - completed

    priority_map = {1: 'High', 2: 'Medium', 3: 'Low'}
    time_per_priority = {'High': 0, 'Medium': 0, 'Low': 0}
    for task in tasks:
        label = priority_map[task['priority']]
        time_per_priority[label] += task['duration'] / 60

    #  Generate Pie Chart - Completion
    fig1, ax1 = plt.subplots()
    ax1.pie([completed, missed], labels=['Completed', 'Missed'],
            autopct='%1.1f%%', colors=['#2ecc71', '#e74c3c'])
    ax1.set_title('Task Completion Overview')
    chart1_path = 'chart1.png'
    plt.savefig(chart1_path)
    plt.close(fig1)

    #  Generate Bar Chart - Time Spent
    fig2, ax2 = plt.subplots()
    ax2.bar(time_per_priority.keys(), time_per_priority.values(),
            color=['#e74c3c', '#f39c12', '#2ecc71'])
    ax2.set_ylabel('Minutes')
    ax2.set_title('Time Spent per Priority')
    chart2_path = 'chart2.png'
    plt.savefig(chart2_path)
    plt.close(fig2)

    #  Generate PDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Smart Scheduler Report", ln=True, align="C")
    pdf.ln(10)

    #  Charts section
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "Analytics Overview:", ln=True)
    pdf.image(chart1_path, x=10, y=None, w=90)
    pdf.image(chart2_path, x=110, y=pdf.get_y(), w=90)
    pdf.ln(80)

    #  Table Header
    pdf.set_font("Arial", 'B', 12)
    pdf.set_fill_color(200, 220, 255)
    headers = ["Task", "Start", "End", "Priority", "Duration"]
    for h in headers:
        pdf.cell(40 if h == "Task" else 35, 10, h, border=1, fill=True)
    pdf.ln()

    # Task Rows
    pdf.set_font("Arial", '', 11)
    for task in tasks:
        priority_label = priority_map[task['priority']]
        color = {
            "High": (220, 50, 50),
            "Medium": (255, 140, 0),
            "Low": (50, 205, 50)
        }[priority_label]
        pdf.set_text_color(*color)

        pdf.cell(40, 10, task['task_name'], border=1)
        pdf.cell(35, 10, task['start_time'].strftime('%Y-%m-%d %H:%M'), border=1)
        pdf.cell(35, 10, task['end_time'].strftime('%Y-%m-%d %H:%M'), border=1)
        pdf.cell(35, 10, priority_label, border=1)
        pdf.cell(35, 10, f"{int(task['duration']//60)} mins", border=1)
        pdf.ln()

    pdf.set_text_color(0, 0, 0)

    #  Export PDF
    output_path = "smart_schedule_report_with_charts.pdf"
    pdf.output(output_path)

    #  Cleanup chart images
    os.remove(chart1_path)
    os.remove(chart2_path)

    return send_file(output_path, as_attachment=True, download_name="smart_schedule_report_with_charts.pdf")


if __name__ == "__main__":
    app.run(debug=True)
