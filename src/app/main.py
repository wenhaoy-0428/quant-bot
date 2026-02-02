from core.services import exchange_service

def main():
    exchange_service.reload_markets()

if __name__ == "__main__":
    main()