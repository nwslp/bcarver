"""
--- bcarver ---
file carving utility based on a set of file carving patterns

dev : nwslp
"""

import argparse
import os
import sys
import yaml
from tqdm import tqdm


def parse_args():
    """ args parsing """
    parser = argparse.ArgumentParser(
        description="bcarver - file carving utility based on a set of file carving patterns"
    )
    
    parser.add_argument('-o', '--output-dir', default='carved_files', help='directory for carved files (\'carved_files\' by default)')
    parser.add_argument('-s', '--skip', type=int, default=0, help='skip N bytes in input_file (default: 0)')
    parser.add_argument('-b', '--block-size', type=int, default=8192, help='read block size (default: 8192)')
    parser.add_argument('-c', '--config', required=True, help='YAML-config with signatures')
    parser.add_argument('input_file', help='path to a image file or raw device (required)')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()
    
def load_config(config_path: str):
    """ config load """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if 'file_types' not in config or not isinstance(config['file_types'], list):
            raise ValueError("No 'file_types' list found in config")

        file_types = []
        max_header_len = 0
        max_footer_len = 0

        for item in config['file_types']:
            if any(k not in item for k in ('name', 'header')):
                raise ValueError(f"Invalid file type: {item}")

            file_types.append({
                'name': item['name'],
                'header': bytes.fromhex(item['header']),
                'footer': bytes.fromhex(item['footer']) if item.get('footer') else b'',
                'max_size': item.get('max_size', 25 * 1024 * 1024) # 25Mb by default
            })
            max_header_len = max(max_header_len, len(file_types[-1]['header']))
            max_footer_len = max(max_footer_len, len(file_types[-1]['footer']))
            
        return file_types, max_header_len, max_footer_len

    except Exception as e:
        print(f"Config loading error: {e}")
        sys.exit(1)

def scan_for_headers(input_path: str, file_types: list, start_offset: int, block_size: int, max_header_len: int):
    """ Block by block search of the all headers in a file """
    candidates = []
    overlap = max_header_len-1
    prev_chunk = b''

    try:
        with open(input_path, 'rb') as f:
            f.seek(start_offset)
            total_size = os.path.getsize(input_path) if os.path.isfile(input_path) else None
            
            pbar = tqdm(
                total=total_size,
                initial=start_offset,
                unit="B",
                mininterval=0.5,
                unit_scale=True,
                dynamic_ncols=True,
                leave=False
            )

            while chunk := f.read(block_size):
                search_buf = prev_chunk + chunk
                pbar.update(len(chunk))
                
                for ft in file_types:
                    pos = 0
                    while (pos := search_buf.find(ft['header'], pos)) != -1:
                        # header was found
                        offset = f.tell() - len(search_buf) + pos
                        candidates.append((offset, ft))
                        pos += 1
                
                # exclude case when footer is on boundary of chunks
                prev_chunk = chunk[-overlap:]
                
            pbar.close()

        # returns a list of potential files. (offset, file type)
        return sorted(candidates)

    except PermissionError:
        print(f"(x) no permission to access {input_path}. Use sudo for /dev/* devices.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"(x) SIGINT")
        return sorted(candidates) # not interrupt; save the files found
    except Exception as e:
        print(f"(x) read error: {e}")
        sys.exit(1)

def carve_files(input_path: str, output_dir: str, candidates: list, block_size: int, max_footer_len: int):
    """ Block by block search for all potential files;
        extract and log files"""
    count = 0
    overlap = max_footer_len-1 # catching footers that cross chunks

    try:
        with open(input_path, 'rb') as f:
            for offset, ft in candidates:
                f.seek(offset)

                pbar = tqdm(
                    total=ft['max_size'],
                    unit="B",
                    mininterval=0.5,
                    unit_scale=True,
                    dynamic_ncols=True,
                    leave=False
                )
                
                ext_dir = os.path.join(output_dir, ft['name'])
                os.makedirs(ext_dir, exist_ok=True)
                filename = f"{offset:x}.{ft['name']}"
                full_path = os.path.join(ext_dir, filename)

                with open(full_path, 'wb') as out:
                    if ft['footer']:
                        prev_chunk = b''

                        while chunk := f.read(block_size):
                            pbar.update(len(chunk))

                            if (f.tell() - offset) > ft['max_size']:
                                # reach the limit
                                forcut = f.tell() - offset - ft['max_size']
                                out.write(chunk[:-forcut])
                                break
                            
                            search_buf = prev_chunk + chunk
                            
                            if (footer_pos := search_buf.find(ft['footer'])) == -1:
                                # footer was not found in chunk
                                out.write(chunk)
                                prev_chunk = chunk[-overlap:]
                            else:
                                # footer was found
                                chunk_pos = footer_pos - len(prev_chunk)
                                out.write(chunk[:chunk_pos + len(ft['footer'])])
                                break
                    else:
                        # no footer
                        out.write(f.read(ft['max_size']))
                        pbar.update(ft['max_size'])

                    fsize = out.tell()
                    pbar.close()
                    count += 1
                
                print(f"\t{filename}\t{hsize(fsize)}\t@ offset {hex(offset)}")
        
        # returns the number of carved files
        return count
    
    except KeyboardInterrupt:
        print(f"(x) SIGINT")
        return count # not interrupt
    except Exception as e:
        print(f"(x) read error: {e}")
        sys.exit(1)

def hsize(n: int | float) -> str:
    # human-readable byte size converter
    for unit in " KMGTPE":
        if n < 1024:
            return f"{round(n,1)}{unit}B"
        n /= 1024

def main():
    args = parse_args()

    # verify args
    if not os.path.exists(args.input_file):
        print(f"(x) file/device '{args.input_file}' does not exist")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    
    file_types, max_h, max_f = load_config(args.config)
    print(f"Loaded {len(file_types)} file types")
    
    print("-> Searching for headers..")
    candidates = scan_for_headers(args.input_file, file_types, args.skip, args.block_size, max_h)
    print(f"   Found {len(candidates)} candidate files")
    
    print("-> Carving files..")
    num_of_files = carve_files(args.input_file, args.output_dir, candidates, args.block_size, max_f)


    print(f"(v) Done! {num_of_files} files successfully carved out.")


if __name__ == "__main__":
    main()
