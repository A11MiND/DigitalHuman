"""一次性迁移：把线上旧容器里用户创建的角色搬到持久化 Volume。

旧版本把用户角色写在 characters/（来自 git 的临时文件系统），重新部署就会丢。
新版本改存 data/characters/。部署新版本【之前】，在还在运行的旧容器里跑这个脚本，
把 characters/ 里不属于 git 的角色目录复制到 data/characters/，并补上 owner /
visibility 字段；部署后新代码会直接从 data/characters/ 加载，id 不变。

用法（在本机经 railway ssh 把脚本送进旧容器执行）：
    railway ssh -- python3 - < scripts/migrate_user_characters.py            # 只看计划
    railway ssh -- python3 - --apply < scripts/migrate_user_characters.py    # 真正复制

可选 --visibility public|private|system（默认 private：只有创建者和管理员可见；
public：创建者公开给所有人；system：当作平台系统角色）。
只复制、不删除旧目录，重复执行会跳过已经迁移过的角色。
"""
import json
import shutil
import sys
from pathlib import Path

# git 里的系统角色——这些随代码部署，不需要迁移
SYSTEM_IDS = {
    "character-49fd372d", "character-b4e8368c", "elizabeth-i", "maryknoll-teacher",
    "munich-airport", "qin-shihuang", "vienna-airport", "you-beauty-advisor", "you-beauty-newclient",
}

SRC = Path("characters")
DEST = Path("data/characters")


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    visibility = "private"
    if "--visibility" in argv:
        visibility = (argv[argv.index("--visibility") + 1:] or [""])[0]
        if visibility not in ("private", "public", "system"):
            print("✗ --visibility 只能是 private / public / system")
            return 1
    base = Path("/app") if Path("/app/characters").is_dir() else Path(".")
    src, dest = base / SRC, base / DEST
    if not (base / "data").is_dir():
        print(f"✗ {base / 'data'} 不存在——Volume 没挂上？中止")
        return 1

    todo = []
    for d in sorted(src.iterdir()):
        cfg_path = d / "character.json"
        if not d.is_dir() or d.name.startswith(".") or d.name in SYSTEM_IDS or not cfg_path.is_file():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        target = dest / d.name
        status = "已迁移，跳过" if target.exists() else "待迁移"
        print(f"{d.name}\t{cfg.get('name', '')}\tcreated_by={cfg.get('created_by', '') or '(无)'}\t{status}")
        if not target.exists():
            todo.append((d, target, cfg))

    if not todo:
        print("没有需要迁移的角色")
        return 0
    if not apply:
        print(f"\n以上 {len(todo)} 个角色待迁移（visibility={visibility}）。确认后加 --apply 执行。")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    for d, target, cfg in todo:
        tmp = target.with_name(f".{target.name}.migrating")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(d, tmp)
        owner = cfg.get("created_by") or ""
        if owner:
            cfg["owner"] = owner
        # 没有创建者可归属的角色只能设为系统角色，否则除管理员外谁都看不到
        cfg["visibility"] = visibility if owner else "system"
        (tmp / "character.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(target)
        print(f"✓ {d.name} → {target}（owner={owner or '(无)'}, visibility={cfg['visibility']}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
