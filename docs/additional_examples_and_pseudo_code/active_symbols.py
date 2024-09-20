from tekhsi import TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    print(connection.activesymbols)
