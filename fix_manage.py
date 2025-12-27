
with open('manage.sh', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Keep lines 1 to 964 (indices 0 to 963)
# Keep lines 1280 to end (indices 1279 to end)

part1 = lines[:964]
part2 = lines[1279:]

new_content = "".join(part1 + part2)

with open('manage.sh', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"Fixed manage.sh. Total lines: {len(part1) + len(part2)}")
