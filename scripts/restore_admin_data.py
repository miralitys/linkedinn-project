#!/usr/bin/env python3
"""Восстановить данные для miralitys@gmail.com: скопировать из user_id=1 или привязать user 1."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.db import init_db, async_session_maker
from app.models import KnowledgeBase, User


async def restore_admin_data():
    """Привязать user 1 к miralitys@gmail.com и/или скопировать данные."""
    await init_db()

    async with async_session_maker() as session:
        # Найти пользователя miralitys@gmail.com
        r = await session.execute(select(User).where(User.email == "miralitys@gmail.com"))
        admin_user = r.scalar_one_or_none()

        # Найти user 1
        r1 = await session.execute(select(User).where(User.id == 1))
        user1 = r1.scalar_one_or_none()

        if not user1:
            print("User с id=1 не найден. Создаём...")
            pw = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.Rb4"  # bcrypt hash of "restore"
            user1 = User(
                email="miralitys@gmail.com",
                password_hash=pw,
                role="admin",
                approval_status="approved",
            )
            session.add(user1)
            await session.commit()
            await session.refresh(user1)
            print(f"✓ User 1 создан: {user1.email}")

        # Если admin_user существует и id != 1 — привязать email к user 1
        if admin_user and admin_user.id != 1:
            print(f"Найден miralitys@gmail.com с user_id={admin_user.id}.")
            print("Обновляем user 1: email = miralitys@gmail.com")
            user1.email = "miralitys@gmail.com"
            await session.commit()
            print("✓ Теперь при входе miralitys@gmail.com следует использовать user_id=1")
            print("  (укажите AUTH_ADMIN_EMAIL=miralitys@gmail.com в .env)")

        # Проверить, есть ли данные в KnowledgeBase для user 1
        keys_to_check = ["setup_authors:1", "authors:1", "setup_products:1", "products:1", "setup_icp_raw:1", "saved_subreddits:1"]
        found = []
        for key in keys_to_check:
            r = await session.execute(select(KnowledgeBase).where(KnowledgeBase.key == key))
            row = r.scalar_one_or_none()
            if row and row.value:
                found.append(key)
        if found:
            print(f"✓ Найдены данные для user 1: {', '.join(found)}")
        else:
            print("Данных в KnowledgeBase для user 1 нет. Добавьте авторов/продукты в Settings.")


if __name__ == "__main__":
    asyncio.run(restore_admin_data())
