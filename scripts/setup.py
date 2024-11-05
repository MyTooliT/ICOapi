import os

def ensure_folder_exists(path):
    # Check if the folder already exists
    if not os.path.exists(path):
        # If not, create the folder
        os.makedirs(path)
        print(f"Folder created at: {path}")
    else:
        print(f"Folder already exists at: {path}")