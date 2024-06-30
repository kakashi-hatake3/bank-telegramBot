from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session

from config import DATABASE_URL

Base = declarative_base()

DATABASE_URL = DATABASE_URL

engine = create_engine(DATABASE_URL, echo=True)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)


def get_session():
    return Session()


def close_session():
    Session.remove()
