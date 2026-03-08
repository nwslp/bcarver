# bcarver

A simple file carving utility that extracts files from disk images or raw devices based on predefined signatures (headers and footers) specified in a YAML configuration file.

## Features

- Scans for file headers in block-based reads to handle large inputs efficiently.
- Supports optional footers for precise file extraction.
- Configurable maximum file size to prevent excessive carving.
- Progress bars for scanning and carving operations using `tqdm`.
- Handles interruptions gracefully, saving partial results.
- Works with files or raw devices (e.g., `/dev/sda` – use sudo for permissions).
- Outputs carved files organized by type in a specified directory.

## Requirements

- Python 3.8+
- Dependencies: `pyyaml`, `tqdm`

Install dependencies with:
```
pip install pyyaml tqdm
```

## Installation

Clone the repository:
```
git clone https://github.com/nwslp/bcarver.git
uv tool install ./bcarver
```

## Usage

Run the script with:
```
python bcarver.py [options] input_file
```

### Options

- `-o, --output-dir`: Directory for carved files (default: `carved_files`).
- `-s, --skip`: Skip N bytes in input_file (default: 0).
- `-b, --block-size`: Read block size in bytes (default: 8192).
- `-c, --config`: Path to YAML config file with signatures (required).
- `input_file`: Path to disk image file or raw device (required).

Example:
```
python bcarver.py -c config.yaml -o carved_files /dev/sda
```

## Configuration

The config is a YAML file with a list of `file_types`. Each type must include:

- `name`: File extension or type name (used for output subdirectory and file extension).
- `header`: Hex string for the file header (required).
- `footer`: Hex string for the file footer (optional; if absent, carves up to `max_size`).
- `max_size`: Maximum bytes to carve if no footer found (default: 25MB).

Example `signatures.yaml`:
```yaml
file_types:
  - name: "jpg"
    header: "FFD8FFE0"
    footer: "FFD9"
    max_size: 31457280

  - name: "png"
    header: "89504E470D0A1A0A"
    footer: "49454E44AE426082"
    max_size: 52428800

  - name: "gif"
    header: "474946383961"
    footer: "00003b"
    max_size: 131072
```

Headers and footers are hex bytes. Ensure they are valid hex.

## How It Works

1. Loads file types from YAML.
2. Scans the input for headers, handling block overlaps to avoid misses.
3. For each candidate header, carves until footer or max_size, saving to output dir.

Output example:
```
Loaded 3 file types
-> Searching for headers..
   Found 5 candidate files
-> Carving files..
        400400.png      1.3MB   @ offset 0x400400
        403c3e.jpg      22.8KB  @ offset 0x403c3e
        541400.jpg      16.5KB  @ offset 0x541400
        7e0400.jpg      65.7KB  @ offset 0x7e0400
        7f0c00.gif      61.0KB  @ offset 0x7f0c00
(v) Done! 5 files successfully carved out.
```

## Contributing

Pull requests welcome! For major changes, open an issue first.

## Author

Developed by nwslp.
