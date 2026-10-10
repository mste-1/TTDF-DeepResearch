"""Server account administration. Passwords are never accepted as CLI arguments."""
import argparse
import getpass
import sys

from server.auth import hash_password
from server.config import Settings
from server.db import Database, now
from server.errors import ServiceError


def read_password():
    password = getpass.getpass("密码（至少 10 个字符）: ")
    if getpass.getpass("再次输入密码: ") != password:
        raise ServiceError("PASSWORD_MISMATCH", "两次输入的密码不一致。")
    return password


def main(argv=None):
    parser = argparse.ArgumentParser(description="问砺服务器账号管理")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="创建账号，首次登录须改密")
    create.add_argument("username")
    create.add_argument("--role", choices=("user", "admin"), default="user")
    commands.add_parser("list", help="列出账号（不显示凭证）")
    for command in ("disable", "enable", "reset"):
        commands.add_parser(command).add_argument("username")
    args = parser.parse_args(argv)
    database = Database(Settings.from_env())
    database.initialize()
    try:
        if args.command == "create":
            user_id = database.create_user(args.username, read_password(), args.role)
            print(f"已创建 {args.username} ({user_id})，首次登录需要修改密码。")
        elif args.command == "list":
            with database.read() as con:
                rows = con.execute("SELECT username,role,enabled,must_change_password FROM users ORDER BY created_at").fetchall()
            for row in rows:
                print(f"{row['username']}\t{row['role']}\t{'启用' if row['enabled'] else '禁用'}\t{'待改密' if row['must_change_password'] else '已改密'}")
        else:
            encoded = hash_password(read_password()) if args.command == "reset" else None
            with database.transaction() as con:
                user = con.execute("SELECT id FROM users WHERE username=?", (args.username,)).fetchone()
                if not user:
                    raise ServiceError("USER_NOT_FOUND", "账号不存在。")
                if args.command == "reset":
                    con.execute("UPDATE users SET password_hash=?,must_change_password=1,password_changed_at=? WHERE id=?", (encoded, now(), user["id"]))
                else:
                    con.execute("UPDATE users SET enabled=? WHERE id=?", (int(args.command == "enable"), user["id"]))
                if args.command != "enable":
                    con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            print("账号状态已更新。")
        return 0
    except ServiceError as exc:
        print(exc.message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
