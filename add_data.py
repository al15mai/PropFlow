income = []
spending = []
import sys

print("exiting...")
sys.exit(0)
csv_str = """Patriei,23.12.2024,"245,53 lei","-245,53 lei","-107,18 lei","-99,99 lei","-38,36 lei","0,00 lei",Cash in/Cash out,OK,Noiembrie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,23.12.2024,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Decembrie,Chirie,,,,
Patriei,23.12.2024,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Ianuarie,Chirie,,,,
Patriei,02.01.2025,"168,32 lei","-168,32 lei","-105,10 lei","-63,22 lei","0,00 lei","0,00 lei",Cash in/Cash out,OK,Decembrie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,14.02.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Februarie,Chirie,,,,
Patriei,14.02.2025,"499,23 lei","-499,23 lei","-319,79 lei","-14,27 lei","-165,17 lei","0,00 lei",Cash in/Cash out,OK,Ianuarie,Utilitati Gaz Curent Apa Asociatie,Diferenta gaz si asociatie:,"-119,37 lei",,
Patriei,09.04.2025,"370,50 lei","-370,50 lei","-214,83 lei","-97,24 lei","-58,43 lei","0,00 lei",Cash in/Cash out,OK,Februarie,Utilitati Gaz Curent Apa Asociatie,Februarie + dif:,"-489,87 lei",,
Patriei,09.04.2025,"306,46 lei","-306,46 lei","-166,74 lei","-12,37 lei","-127,35 lei","0,00 lei",Cash in/Cash out,OK,Martie,Utilitati Gaz Curent Apa Asociatie,Februarie + dif + GAZ martie,"-656,61 lei",,
Patriei,04.03.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Martie,Chirie,,,,
Patriei,24.03.2025,,"-118,00 lei","-118,00 lei",,,"-118,00 lei",Cash out,OK,Martie,Impozit,,,,
Patriei,09.04.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Aprilie,Chirie,Februarie + dif + GAZ martie + chirie,"-2.256,61 lei",,
Patriei,27.05.2025,"420,81 lei","-420,81 lei","-88,37 lei","-174,07 lei","-158,37 lei","0,00 lei",Cash in/Cash out,OK,Aprilie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,27.05.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Mai,Chirie,,"0,00 lei",,
Patriei,27.05.2025,"341,30 lei","-341,30 lei","-75,54 lei","-95,84 lei","-169,92 lei","0,00 lei",Cash in/Cash out,OK,Mai,Utilitati Gaz Curent Apa Asociatie,,"0,00 lei",,
Patriei,27.05.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Iunie,Chirie,,,,
Patriei,26.07.2025,"224,68 lei","-224,68 lei","-59,99 lei","-14,27 lei","-150,42 lei","0,00 lei",Cash in/Cash out,OK,Iunie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,26.07.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Iulie,Chirie,,"0,00 lei",,
Patriei,25.08.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,August,Chirie,,"0,00 lei",,
Patriei,25.08.2025,"335,25 lei","-335,25 lei","-37,97 lei","-170,28 lei","-127,00 lei","0,00 lei",Cash in/Cash out,OK,August,Utilitati Gaz Curent Apa Asociatie,,"0,00 lei",,"-134,91 lei"
Patriei,22.09.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Septembrie,Chirie,,"0,00 lei",,
Patriei,03.11.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",Cash in,OK,Octombrie,Chirie,,"1.600,00 lei",,
Patriei,23.09.2025,"315,98 lei","-315,98 lei","-58,43 lei","-140,96 lei","-116,59 lei","0,00 lei",Cash in/Cash out,OK,Septembrie,Utilitati Gaz Curent Apa Asociatie,,"0,00 lei",,
Patriei,17.12.2025,"268,86 lei","-268,86 lei","-176,09 lei","-92,77 lei",,"0,00 lei",Cash in/Cash out,OK,Octombrie,Utilitati Gaz Curent Apa Asociatie,,"56,74","Aici gaz trebuia 119,35",
Patriei,17.12.2025,"272,10 lei","-272,10 lei",,"-75,73 lei","-196,37 lei","0,00 lei",Cash in/Cash out,OK,Noiembrie,Utilitati Gaz Curent Apa Asociatie,,-3,"Aici asociatie trebuia 199,37",
Patriei,17.12.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",,OK,Noiembrie,Chirie,,"-1.600,00 lei",,
Patriei,17.12.2025,"1.600,00 lei","0,00 lei",,,,"1.600,00 lei",,OK,Decembrie,Chirie,,"-3.200,00 lei",luat 3850,
Patriei,20.12.2025,,"-585,51 lei","-236,43 lei","-183,14 lei","-165,94 lei","-585,51 lei",Cash in/Cash out,Eroare[Cash in/Cash out] venitul diferit de cheltuieli (Cash in-Cash out <> 0),Decembrie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,20.12.2025,,"-419,55 lei","-212,52 lei","-94,44 lei","-112,59 lei","-419,55 lei",Cash in/Cash out,Eroare[Cash in/Cash out] venitul diferit de cheltuieli (Cash in-Cash out <> 0),Ianuarie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,20.12.2025,,"-304,50 lei",,"-97,71 lei","-206,79 lei","-304,50 lei",Cash in/Cash out,Eroare[Cash in/Cash out] venitul diferit de cheltuieli (Cash in-Cash out <> 0),Februarie,Utilitati Gaz Curent Apa Asociatie,,,,
Patriei,20.12.2025,,"-216,26 lei",,,"-216,26 lei","-216,26 lei",Cash in/Cash out,Eroare[Cash in/Cash out] venitul diferit de cheltuieli (Cash in-Cash out <> 0),Februarie,Utilitati Gaz Curent Apa Asociatie,Gunoi anual,,,"""
import csv

csv_reader = csv.reader(csv_str.splitlines())


def clean_amount(s: str) -> float:
    try:
        return (
            float(s.replace(" lei", "").replace(".", "").replace(",", "."))
            if s
            else 0.0
        )
    except Exception as e:
        return 0.0


# ejyll2nxm	2024-12-10	1600	Income			Chirie		fab82y0dj	Transfer	0		0
from api import create_transaction
from models import Transaction
from uuid import uuid4


# create_transaction()


def make_utility_transaction(date, amount, description):
    return Transaction(
        id=uuid4().hex,
        date=date,
        amount=amount,
        type="Expense",
        category="Utilities",
        subcategory=description,
        description=description,
        tenantId="fab82y0dj",
        paymentMethod="Cash",
        isReimbursable=True,
    )


for row in csv_reader:
    date = row[1]

    date_parts = date.split(".")
    date_parsed = f"{date_parts[2]}-{date_parts[1]}-{date_parts[0]}"

    income = clean_amount(row[2])

    gas = clean_amount(row[4]) * -1
    electricity = clean_amount(row[5]) * -1
    water = clean_amount(row[6]) * -1

    if gas > 0 or electricity > 0 or water > 0:

        # print(date, gas, electricity, water)
        # transactions = []
        # if gas > 0:
        #     tx = make_utility_transaction(date_parsed, gas, "Gas")
        #     transactions.append(tx)
        # if electricity > 0:
        #     tx = make_utility_transaction(date_parsed, electricity, "Electricity")
        #     transactions.append(tx)
        # if water > 0:
        #     tx = make_utility_transaction(date_parsed, water, "Water")
        #     transactions.append(tx)
        # print(date, transactions, "\n\n")

        # for trx in transactions:
        #     create_transaction(trx)

        reimbursed = sum([gas, electricity, water])

        print(date, reimbursed, "\n\n")
        reimbursed_tx = Transaction(
            id=uuid4().hex,
            date=date_parsed,
            amount=reimbursed,
            type="Income",
            description="Rambursare utilitati",
            tenantId="fab82y0dj",
            paymentMethod="Cash",
            isReimbursable=False,
        )
        create_transaction(reimbursed_tx)
    # else:
    #     income = Transaction(
    #         id=uuid4().hex,
    #         date=date_parsed,
    #         amount=income,
    #         type="Income",
    #         description="Chirie",
    #         tenantId="fab82y0dj",
    #         paymentMethod="Cash",
    #         isReimbursable=False,
    #     )
    #     create_transaction(income)
    #     print(date, income, "\n\n")
