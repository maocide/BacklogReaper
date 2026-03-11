REM Pull the repository
git clone https://github.com/maocide/BacklogReaper.git

REM Navigate into the project folder
cd BacklogReaper

REM Create the virtual environment
python -m venv venv

REM Activate the virtual environment (Git Bash specific!)
source venv/Scripts/activate

REM Install the dependencies
pip install -r requirements.txt

REM Install pyinstaller
pip install pyinstaller

REM Run the build script
./build.bat