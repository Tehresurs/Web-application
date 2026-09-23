from app.repositories.employees import get_all_employees


employees = get_all_employees()

print("Сотрудники:")
print(employees)
