#!/usr/bin/env python3
"""Скрипт для создания админа miralitys@gmail.com"""
import asyncio
import bcrypt
import sys
from pathlib import Path

# Добавляем корень проекта в путь
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import settings
from app.db import init_db, async_session_maker
from app.models import User, UserRole
from sqlalchemy import select


async def create_admin():
    """Создаёт админа miralitys@gmail.com, если его ещё нет."""
    await init_db()
    
    async with async_session_maker() as session:
        email = "miralitys@gmail.com"
        
        # Проверяем, существует ли уже пользователь
        r = await session.execute(select(User).where(User.email == email))
        existing = r.scalar_one_or_none()
        
        if existing:
            if existing.role == UserRole.ADMIN.value:
                print(f"✓ Пользователь {email} уже является админом")
                return
            else:
                # Обновляем роль на админ
                existing.role = UserRole.ADMIN.value
                await session.commit()
                print(f"✓ Пользователь {email} обновлён до админа")
                return
        
        # Создаём нового админа
        # Пароль по умолчанию из .env (если есть) или "admin123"
        password = settings.auth_admin_password or "admin123"
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        
        admin = User(
            email=email,
            password_hash=password_hash,
            role=UserRole.ADMIN.value,
        )
        session.add(admin)
        await session.commit()
        
        print(f"✓ Админ {email} создан успешно")
        print(f"  Пароль: {'(из .env)' if settings.auth_admin_password else 'admin123'}")
        print(f"  Роль: {admin.role}")


if __name__ == "__main__":
    asyncio.run(create_admin())
