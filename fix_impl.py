file1 = "services/orchestrator/architecture_hardening_part14.py"
with open(file1, "r") as f:
    content = f.read()

content = content.replace('\\"', '"')

with open(file1, "w") as f:
    f.write(content)
