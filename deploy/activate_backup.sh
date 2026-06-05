#!/bin/bash
# Helper script to activate daily QATrack+ database backups via cron
set -e

# Automatically find QATrack+ root directory based on the location of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
QATRACK_DIR="$(dirname "$SCRIPT_DIR")"

echo "QATrack+ Directory detected as: $QATRACK_DIR"

if [ ! -f "$QATRACK_DIR/manage.py" ]; then
    echo "Error: manage.py not found in $QATRACK_DIR. Are you running this script from the deploy/ directory?"
    exit 1
fi

echo ""
echo "This script will add a daily cron job to run 'python manage.py backup_site' at 2:00 AM."
read -p "Do you want to proceed? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]
then
    # Assuming python is available in the environment or virtual environment
    # In a typical Linux setup, we'd use the virtual environment's python.
    # Let's try to detect the venv if it exists in the QATrack directory, otherwise default to python3
    PYTHON_EXEC="python3"
    if [ -f "$QATRACK_DIR/venv/bin/python" ]; then
        PYTHON_EXEC="$QATRACK_DIR/venv/bin/python"
    elif [ -f "$QATRACK_DIR/env/bin/python" ]; then
        PYTHON_EXEC="$QATRACK_DIR/env/bin/python"
    fi

    CRON_CMD="0 2 * * * cd $QATRACK_DIR && $PYTHON_EXEC manage.py backup_site >> /var/log/qatrack_backup.log 2>&1"

    # Check if job already exists
    if crontab -l 2>/dev/null | grep -q "manage.py backup_site"; then
        echo "A backup cron job already exists in your crontab. Skipping installation."
    else
        # Add to crontab
        (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
        echo "Successfully added backup cron job."
        echo "The backup command will run every day at 2:00 AM."
    fi
else
    echo "Aborted."
fi
