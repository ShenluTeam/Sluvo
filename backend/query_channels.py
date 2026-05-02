import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append('e:/ljtpc/work/AIdrama/backend')

from database import engine
from sqlmodel import Session, select
from models import ChannelSettings

def main():
    with Session(engine) as session:
        channels = session.exec(select(ChannelSettings)).all()
        for c in channels:
            print(f"ID: {c.channel_id}, Name: {c.name}, Cost: {c.cost_points}, Active: {c.is_active}")

if __name__ == '__main__':
    main()
