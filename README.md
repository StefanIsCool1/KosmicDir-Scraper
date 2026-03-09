1. Uses playwright to fetch responses from target websites directory
2. Flexible usage allowing user to import CSV (make sure links start from first column first row")
3. Dumps the directory data in Data-dump (.json format)

   
UnderDeck Scraper

A web scraping tool that captures directory and member data from websites.

Prerequisites

You'll need these installed first:
you guys proablay have this but ye
Python 3.8 or higher (check with python --version or python3 --version)
Node.js 14 or higher (check with node --version)
npm (comes with Node.js, check with npm --version)

Installation

1. First to get the code 
```
git clone your-repo-url
cd UnderDeckScraper
```
2. Install Python packages
```
pip install flask flask-cors playwright
```
3. Install Playwright browsers
```
playwright install chromium
```
4. Install frontend dependencies
```
cd frontend
npm install
cd ..
```
TO RUN THE APP

(Run app.py)

python app.py (or python3 app.py on Mac/Linux)

The backend will run at http://localhost:5000

Start the frontend (in a new terminal)

cd frontend
npm start

The frontend will open at http://localhost:3000

Usage

Open http://localhost:3000 in your browser (Chrome or Firefox works best, Safari can be tricky :/)
Choose either "Single Link" or "CSV File"
Enter a URL or upload a CSV file with links
Click "run scrap" and wait :))
Results save to the Data-dump folder :)


Troubleshooting

CORS errors
Make sure both backend and frontend are running
Backend should be on port 5000, frontend on port 3000

No results
Some websites block scrapers, try a different site :0
Check the terminal for error messages
Look in the Data-dump folder to see if files were created

Safari issues
Use Chrome or Firefox instead
They play nicer with local development :)

File structure

UnderDeckScraper/
app.py - Flask backend
Bot/ - Scraping logic
FetchXHR.py
Data-dump/ - Saved results (created automatically)
frontend/ - React frontend
requirements.txt - Python dependencies

Need help?

If something isn't working, check that:

Python packages are installed (```pip list | grep -E "flask|flask-cors|playwright"```)
Backend is running (you should see output in the terminal)
Frontend is running (you should see output in the other terminal)
All pip and npm install commands completed without errors
Both servers are running (you should see output in both terminals)
You're using Chrome or Firefox (Safari can be moody >:))

Good luck scraping! :D
