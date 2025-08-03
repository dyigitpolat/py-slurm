#!/bin/bash
ENV_DIR=venv

# Create virtual environment if it does not exist
if [ ! -d "$ENV_DIR" ]; then
    echo "creating remote venv in $ENV_DIR..."
    python3 -m venv $ENV_DIR
fi

# Activate the environment
echo "activating remote venv..."
source $ENV_DIR/bin/activate

# Upgrade pip and install dependencies
echo "upgrading pip and installing dependencies..."
pip install --upgrade pip
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
else
    pip install torch torchvision
fi

echo "remote env setup complete." 