from infrastructure import Base, engine
from models import URL, Click, ReferrerState


def init_db():
    print("Creating tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully.")

if __name__ == "__main__":
    init_db()