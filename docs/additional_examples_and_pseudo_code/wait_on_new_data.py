from tekhsi import AcqWaitOn, TekHSIConnect

with TekHSIConnect("192.168.0.1:5000") as connection:
    with connection.access_data(AcqWaitOn.NewData):
        ...
