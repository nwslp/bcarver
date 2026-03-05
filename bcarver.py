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
    """ Обработка аргументов """
    parser = argparse.ArgumentParser(
        description="bcarver - file carving utility based on a set of file carving patterns"
    )
    
    parser.add_argument('-o', '--output-dir', default='carved_files', help='directory for carved files (\'carved_files\' by default)')
    parser.add_argument('-s', '--skip', type=int, default=0, help='skip N ibs sized input blocks (default: 0)')
    parser.add_argument('-b', '--block-size', type=int, default=8192, help='read block size (default: 8192)')
    parser.add_argument('-c', '--config', required=True, help='YAML-config with signatures')
    parser.add_argument('input_file', help='path to a image file or raw device (required)')
    
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args()
    
def load_config(config_path: str):
    """ Обработка конфигурационного файла. """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        if 'file_types' not in config or not isinstance(config['file_types'], list):
            raise ValueError("No 'file_types' list found in config")

        file_types = []
        max_header_len = 0
        max_footer_len = 0

        for item in config['file_types']:
            file_types.append({
                'name': item['name'],
                'header': bytes.fromhex(item['header']),
                'footer': bytes.fromhex(item['footer']),
                'max_size': item.get('max_size', 25 * 1024 * 1024) # 25Mb by default
            })
            max_header_len = max(max_header_len, len(file_types[-1]['header']))
            max_footer_len = max(max_footer_len, len(file_types[-1]['footer']))
            
        return file_types, max_header_len, max_footer_len

    except Exception as e:
        print(f"Config loading error: {e}")
        sys.exit(1)

def scan_for_headers(input_path: str, file_types: list, start_offset: int, block_size: int, max_header_len: int):
    """ Поблочный поиск всех хедеров в файле """
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
                pbar.update(block_size)
                
                for ft in file_types:
                    pos = 0
                    while (pos := search_buf.find(ft['header'], pos)) != -1:
                        # хедер найден
                        abs_pos = f.tell() - block_size - overlap + pos
                        candidates.append((abs_pos, ft))
                        pos += 1
                
                # исключаем вариант его локации на границе блоков
                prev_chunk = chunk[-overlap:]
                
            pbar.close()
            
    except PermissionError:
        print(f"(x) no permission to access {input_path}. Use sudo for /dev/* devices.")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"(x) SIGINT")
        return sorted(candidates) # не прерывать; найденные файлы завершить
    except Exception as e:
        print(f"(x) read error: {e}")
        sys.exit(1)
        
    return sorted(candidates)  # список (offset, ft)

def carve_files(input_path: str, output_dir: str, candidates: list, block_size: int, max_footer_len: int):
    """ Поблочный поиск футеров для всех потенциальных файлов;
        Запись и логирование извлеченных файлов."""
    count = 0
    overlap = max_footer_len-1
    prev_chunk = b''
    
    try:
        with open(input_path, 'rb') as f:
            for offset, ft in candidates:
                f.seek(offset)
                file_data=b''
                
                
                pbar = tqdm(
                    total=ft['max_size'],
                    unit="B",
                    mininterval=0.5,
                    unit_scale=True,
                    dynamic_ncols=True,
                    leave=False
                )
                
                if ft['footer']:
                    while chunk := f.read(block_size):
                        pbar.update(block_size)
                        
                        if (f.tell() - offset) > ft['max_size']:
                            # достигнут предел максимального размера файла
                            file_data += chunk
                            break
                        search_buf = prev_chunk + chunk
                        
                        if (footer_pos := search_buf.find(ft['footer'])) == -1:
                            # футер в чанке не найден
                            file_data += chunk
                        else:
                            # футер найден
                            file_data += search_buf[:footer_pos + len(ft['footer'])]
                            break
                            
                        # исключаем вариант его локации на границе блоков
                        prev_chunk = chunk[-overlap:]
                else:
                    # если футер не назначен
                    file_data = f.read(ft['max_size'])
                
                pbar.close()
                count += 1
                           
                # записываем найденный файл
                filename = f"{count:06d}.{ft['name']}"
                full_path = os.path.join(output_dir, filename)

                with open(full_path, 'wb') as out:
                    out.write(file_data)
                
                print(f"\t{filename}\t{hsize(len(file_data))}\t@ offset {hex(offset)}")
                
        return count
    
    except KeyboardInterrupt:
        print(f"(x) SIGINT")
        sys.exit(1)
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
    # Парсинг аргументов
    args = parse_args()

    # Верификация вводных
    if not os.path.exists(args.input_file):
        print(f"(x) file/device '{args.input_file}' does not exist")
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)
    
    file_types, max_h, max_f = load_config(args.config)
    print(f"Loaded {len(file_types)} file types")
    
    # Поиск заголовков
    print("-> Searching for headers..")
    candidates = scan_for_headers(args.input_file, file_types, args.skip, args.block_size, max_h)
    print(f"   Found {len(candidates)} candidate files")
    
    # Извлечение файлов
    print("-> Carving files..")
    num_of_files = carve_files(args.input_file, args.output_dir, candidates, args.block_size, max_f)


    print(f"(v) Done! {num_of_files} files successfully carved out.")


if __name__ == "__main__":
    main()
