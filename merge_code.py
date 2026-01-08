import os

# 定义要合并的文件后缀
extensions = ('.py', '.html')
output_file = 'merged_project_code.txt'

print("正在合并文件，请稍候...")

with open(output_file, 'w', encoding='utf-8') as outfile:
    for root, dirs, files in os.walk('.'):
        # 排除虚拟环境文件夹，防止扫描成千上万个库文件
        if 'venv' in root or '.venv' in root:
            continue
            
        for file in files:
            if file.endswith(extensions):
                file_path = os.path.join(root, file)
                outfile.write(f"\n{'='*50}\n")
                outfile.write(f"FILE: {file_path}\n")
                outfile.write(f"{'='*50}\n\n")
                
                try:
                    # 尝试用 utf-8 读取，如果失败则尝试 gbk (处理中文乱码的关键)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as infile:
                            outfile.write(infile.read())
                    except UnicodeDecodeError:
                        with open(file_path, 'r', encoding='gbk') as infile:
                            outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"[无法读取文件: {file_path}, 错误: {e}]\n")
                outfile.write("\n")

print(f"成功！合并后的文件已生成: {output_file}")