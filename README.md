# ProgressTracker

## Overview

The Weighted Progress Tracker — v1.0 is a desktop productivity app written in Python with Tkinter. Unlike a simple to-do list, this tool is designed for students, professionals, and anyone managing multiple assignments or projects with different priorities.

You can track tasks not just by completion, but by weight, estimated effort (hours), and deadlines. This gives you a more accurate picture of how much work remains — whether you’re finishing a college course, balancing freelance projects, or handling personal goals.

At the top of the app, you can set a personal goal statement and add an optional goal image for visual motivation. The app also provides weekly views, notifications, and filtering by tags, making it a full-featured lightweight project manager.

## Key Features

### Three progress modes
  - Weighted (progress by task weight)
  - Unweighted (simple task counts)
  - Hours-weighted (progress by estimated hours)
  
### Goal panel
  - Write a goal statement at the top of the app
  - Add an optional image (PNG/GIF) for extra motivation

### Weekly planner view
  - See tasks due today, tomorrow, and the upcoming week
  - Urgency badges: 🔥 today, ⚠ tomorrow, ⏳ soon, • later

### Tags & filtering
  - Organize tasks by custom tags
  - Filter your view by tag

### Notifications & reminders
  - Warnings for overdue and upcoming tasks
  - Optional sound alerts (Windows only)

### Dark mode theme
  - Sleek, modern look for day or night

### Autosave & persistence
  - Work is saved automatically to JSON
  - Load previous state instantly when reopening

### CSV import/export
  - Import tasks from a spreadsheet
  - Export progress for reports or backups

### Inline editing
  - Rename tasks, adjust weights, due dates, and tags directly
  - Toggle status with checkboxes or dropdowns

# Installation
## 1. Clone the repository or Click the green "<>Code" button and "Download ZIP"
Open your terminal (Command Prompt on Windows)
```
git clone https://github.com/JaySofranko/progresstracker.git
```
Then, navigate to the file using this command, or open the file manually
```
cd progresstracker
```

## 2. Install dependencies
Make sure you have Python 3.9+ installed. If not, then go to https://www.python.org/downloads/ and download latest. Then run:
```
pip install -r requirements.txt
```
Dependencies include:
tk (Tkinter, usually comes with Python)
pandas
openpyxl
python-docx
python-pptx
pypandoc
Pillow (for image scaling)

## 3. Run the app in Command Prompt, or double-click the ProgressTracker.py in File Explorer
```
python progresstracker.py
```
The app will open in a Tkinter GUI window.

# License
This project is licensed under the MIT License.

# Support This Project

This app is free and open-source. If you find it useful and want to support development, consider buying me a coffee:

- [Buy Me a Coffee]([https://buymeacoffee.com/jaysofranko])

Your support helps keep the project alive and motivates me to keep improving it. Thanks!
