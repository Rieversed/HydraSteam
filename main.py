import json
import os
from pathlib import Path

def split_json_file(input_file, output_dir, games_per_file=50):
    """Split a JSON file containing game downloads into smaller files."""
    # Create output directory if it doesn't exist
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Read the input JSON file
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Get the downloads list
    downloads = data.get('downloads', [])
    if not downloads:
        print(f"No downloads found in {input_file}")
        return
    
    # Sort downloads by title (case-insensitive)
    downloads.sort(key=lambda x: x.get('title', '').lower())
    
    # Split into chunks
    for i in range(0, len(downloads), games_per_file):
        chunk = downloads[i:i + games_per_file]
        
        # Create chunk data
        chunk_data = {
            "name": f"{data.get('name', 'downloads')}_part_{i//games_per_file + 1}",
            "downloads": chunk
        }
        
        # Determine output filename
        output_file = output_dir / f"{Path(input_file).stem}_part_{i//games_per_file + 1}.json"
        
        # Write chunk to file
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, indent=2, ensure_ascii=False)
        
        print(f"Created {output_file} with {len(chunk)} games")

def main():
    # Configuration
    input_files = ['hydrasteam.json', 'hydrasteam_broad.json']
    output_base_dir = 'split_files'
    games_per_file = 50  # Number of games per output file
    
    # Process each input file
    for input_file in input_files:
        if not os.path.exists(input_file):
            print(f"Warning: {input_file} not found, skipping...")
            continue
        
        output_dir = os.path.join(output_base_dir, os.path.splitext(input_file)[0])
        print(f"\nProcessing {input_file}...")
        split_json_file(input_file, output_dir, games_per_file)
    
    print("\nSplitting complete!")

if __name__ == "__main__":
    main()