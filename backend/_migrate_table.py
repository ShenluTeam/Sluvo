import os
import sys

from sqlalchemy import text
from sqlmodel import Session
from database import engine

def migrate():
    with Session(engine) as session:
        commands = [
            "ALTER TABLE panel ADD COLUMN scene VARCHAR(255);",
            "ALTER TABLE panel ADD COLUMN `character` VARCHAR(255);",
            "ALTER TABLE panel ADD COLUMN image_framing LONGTEXT;",
            "ALTER TABLE panel ADD COLUMN video_prompt LONGTEXT;",
            "ALTER TABLE panel ADD COLUMN original_text LONGTEXT;"
        ]
        for cmd in commands:
            try:
                session.execute(text(cmd))
                print(f"Executed: {cmd}")
            except Exception as e:
                print(f"Error executing {cmd}: {e}")
                session.rollback()
            else:
                session.commit()
                
if __name__ == "__main__":
    migrate()
