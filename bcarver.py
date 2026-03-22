"""
--- bcarver ---
file carving utility based on a set of file carving patterns

dev : nwslp
v1.1

"""

import argparse
import os
import sys
import yaml
from tqdm import tqdm

KBYTE_STEP = 1024
DEFAULT_MAX_SIZE = 25 * (KBYTE_STEP**2) # 25Mb by default


def parse_args():
    """ Initialization of commandline parameters """
    parser = argparse.ArgumentParser(
        description="bcarver - file carving utility based on a set of file carving patterns"
    )
    
    parser.add_argument(
        "-o",
        "--output-dir",
        default="carved_files",
        help="directory for carved files ('carved_files' by default)",
    )
    parser.add_argument(
        "-s",
        "--skip",
        type=int,
        default=0,
        help="skip N bytes in input_file (default: 0)",
    )
    parser.add_argument(
        "-b",
        "--block-size",
        type=int,
        default=8192,
        help="read block size (default: 8192)",
    )
    parser.add_argument(
        "-c", "--config", required=True, help="YAML-config with signatures"
    )
    parser.add_argument(
        "-m",
        "--min-size",
        type=int,
        default=512,
        help="set the minimum size for carved files (ignores and skip smaller matches; default: 512)",
    )
    parser.add_argument(
        "--write-on-maxsize",
        action="store_true",
        help="enables carving of file when footer was not found within max_size specified in the config file.",
    )
    parser.add_argument(
        "input_file", help="path to a image file or raw device (required)"
    )

    return parser.parse_args()


def load_config(config_path: str) -> list:
    """ Load YAML configuration file """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if 'file_types' not in config or not isinstance(config['file_types'], list):
            raise ValueError("'file_types' list missing")

    except (FileNotFoundError, yaml.YAMLError) as e:
        print(f"(x) failed to read or parse config: {e}")
        sys.exit(1)

    except ValueError as e:
        print(f"(x) invalid config structure: {e}")
        sys.exit(1)

    file_types = []
    max_header_len = 0
    max_footer_len = 0

    for item in config['file_types']:
        try:
            if any(k not in item for k in ('name', 'header')):
                raise ValueError(f"Invalid file type: {item}")

            header_bytes = bytes.fromhex(item['header'])
            footer_bytes = bytes.fromhex(item['footer']) if item.get('footer') else b''

        except ValueError:
            print(f"(x) invalid hex string or file type in config for {item}")
            sys.exit(1)

        file_types.append(
            {
                'name': item['name'],
                'header': header_bytes,
                'footer': footer_bytes,
                'max_size': item.get('max_size', DEFAULT_MAX_SIZE)
            }
        )

        max_header_len = max(max_header_len, len(file_types[-1]['header']))
        max_footer_len = max(max_footer_len, len(file_types[-1]['footer']))
            
    return file_types, max_header_len, max_footer_len


def scan_for_headers(
    input_path: str,
    file_types: list,
    start_offset: int,
    block_size: int,
    max_header_len: int
) -> list:
    """ Block by block search of the all headers in a file """
    candidates = []
    overlap = max_header_len - 1
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

                for file_type in file_types:
                    pos = 0
                    while (pos := search_buf.find(file_type['header'], pos)) != -1:
                        # header was found
                        offset = f.tell() - len(search_buf) + pos
                        candidates.append((offset, file_type))
                        pos += 1
                
                # exclude case when footer is on boundary of chunks
                prev_chunk = chunk[-overlap:]

            pbar.close()

        # returns a list of potential files. (offset, file type)
        return candidates

    except PermissionError:
        print(f"(x) no permission to access {input_path}. Use sudo for /dev/* devices.")
        sys.exit(1)

    except KeyboardInterrupt:
        print("(x) SIGINT")
        return candidates # not interrupt; save the files found

    except Exception as e:
        print(f"(x) read error: {e}")
        sys.exit(1)


def carve_files(
    input_path: str,
    output_dir: str,
    candidates: list,
    block_size: int,
    max_footer_len:int,
    min_file_size: int,
    write_on_maxsize: bool
) -> int:
    """ Block by block search for all potential files;
        extract and log files"""
    count = 0
    overlap = max_footer_len - 1 # catching footers that cross chunks

    try:
        os.makedirs(output_dir, exist_ok=True)
        with open(input_path, 'rb') as f:
            for offset, file_type in candidates:
                f.seek(offset)

                pbar = tqdm(
                    total=file_type['max_size'],
                    unit="B",
                    mininterval=0.5,
                    unit_scale=True,
                    dynamic_ncols=True,
                    leave=False
                )

                ext_dir = os.path.join(output_dir, file_type['name'])
                os.makedirs(ext_dir, exist_ok=True)
                filename = f"{offset:x}.{file_type['name']}"
                full_path = os.path.join(ext_dir, filename)

                with open(full_path, 'wb') as out:
                    remove_flag = False

                    if file_type['footer']:
                        prev_chunk = b''

                        while chunk := f.read(block_size):
                            pbar.update(len(chunk))

                            if (f.tell() - offset) > file_type['max_size']:
                                # reach the limit
                                if write_on_maxsize:
                                    forcut = f.tell() - offset - file_type['max_size']
                                    out.write(chunk[:-forcut])
                                else:
                                    # remove the file
                                    remove_flag = True
                                break
                            
                            search_buf = prev_chunk + chunk
                            
                            if (footer_pos := search_buf.find(file_type['footer'])) == -1:
                                # footer was not found in chunk
                                out.write(chunk)
                                prev_chunk = chunk[-overlap:]
                            else:
                                # footer was found
                                chunk_pos = footer_pos - len(prev_chunk)
                                out.write(chunk[:chunk_pos + len(file_type['footer'])])
                                break
                    else:
                        # no footer
                        while chunk := f.read(block_size):
                            pbar.update(len(chunk))
                            if (f.tell() - offset) > file_type['max_size']:
                                # reach the limit
                                forcut = int(f.tell()) - offset - file_type['max_size']
                                out.write(chunk[:-forcut])
                                break
                            else:
                                out.write(chunk)

                    fsize = out.tell()
                    pbar.close()

                    # minsize check
                    if fsize <= min_file_size:
                        remove_flag = True

                    if remove_flag:
                        out.flush()
                        out.close()
                        os.remove(full_path)
                        print(f"\t[file did not pass]\t{hsize(fsize)}\t@ offset {hex(offset)}")
                    else:
                        count += 1
                        print(f"\t{filename}\t{hsize(fsize)}\t@ offset {hex(offset)}")

        # returns the number of carved files
        return count
    
    except KeyboardInterrupt:
        print("(x) SIGINT")
        return count # not interrupt

    except Exception as e:
        print(f"(x) read error: {e}")
        sys.exit(1)


def hsize(n: int | float) -> str:
    # human-readable byte size converter
    for unit in " KMGTPE":
        if n < KBYTE_STEP:
            return f"{round(n,1)}{unit}B"
        n /= KBYTE_STEP


def main():
    args = parse_args()

    # verify args
    if not os.path.exists(args.input_file):
        print(f"(x) file/device '{args.input_file}' does not exist")
        sys.exit(1)
    
    file_types, max_h, max_f = load_config(args.config)
    print(f"Loaded {len(file_types)} file types")
    
    print("-> Searching for headers..")
    candidates = scan_for_headers(
        args.input_file,
        file_types,
        args.skip,
        args.block_size,
        max_h
    )

    print(f"   Found {len(candidates)} candidate files")
    
    print("-> Carving files..")
    num_of_files = carve_files(
        args.input_file,
        args.output_dir,
        candidates,
        args.block_size,
        max_f,
        args.min_size,
        args.write_on_maxsize
    )

    print(f"(v) Done! {num_of_files} files successfully carved out.")


if __name__ == "__main__":
    main()
