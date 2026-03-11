# Pull the repository
git clone https://github.com/maocide/BacklogReaper.git

# Navigate into the project folder
cd BacklogReaper

# Create the virtual environment
python -m venv venv

# Activate the virtual environment (Git Bash specific!)
source venv/Scripts/activate

# Install the dependencies
pip install -r requirements.txt

# Install pyinstaller
pip install pyinstaller

# Run the build script
./build.bat