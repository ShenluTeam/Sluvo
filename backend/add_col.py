from database import engine
from sqlmodel import text

def add_prompt_zh_column():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE panel ADD COLUMN prompt_zh LONGTEXT;"))
            print("Successfully added prompt_zh column to panel table.")
        except Exception as e:
            if "Duplicate column name" in str(e) or "already exists" in str(e):
                print("Column prompt_zh already exists.")
            else:
                print(f"Failed to add column prompt_zh: {e}")

        try:
            conn.execute(text("ALTER TABLE panel MODIFY COLUMN prompt LONGTEXT;"))
            # If the negative prompt gets long later, we alter it too to be safe:
            conn.execute(text("ALTER TABLE panel MODIFY COLUMN negative_prompt LONGTEXT;"))
            conn.commit()
            print("Successfully lengthened prompt and negative_prompt columns to LONGTEXT.")
        except Exception as e:
            print(f"Failed to modify column prompt: {e}")

if __name__ == "__main__":
    add_prompt_zh_column()
