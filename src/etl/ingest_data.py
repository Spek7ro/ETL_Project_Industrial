import kagglehub
import shutil
import os
import glob

def ingest_data():
    print("Downloading dataset from Kaggle...")
    # Download latest version
    path = kagglehub.dataset_download("mujtabamatin/dataset-for-machine-failure-detection")
    print("Path to downloaded files:", path)
    
    # Target directory
    landing_dir = 'data/landing'
    os.makedirs(landing_dir, exist_ok=True)
    
    # Find CSV files in the downloaded path
    csv_files = glob.glob(os.path.join(path, "*.csv"))
    
    if not csv_files:
        print("No CSV files found in the downloaded dataset.")
        return
        
    for csv_file in csv_files:
        filename = os.path.basename(csv_file)
        dest_path = os.path.join(landing_dir, filename)
        shutil.copy(csv_file, dest_path)
        print(f"Moved {filename} to {landing_dir}")

if __name__ == "__main__":
    ingest_data()
