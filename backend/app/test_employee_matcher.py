from app.services.employee_matcher import find_employee_by_full_name


def test_employee(full_name):
    print()
    print("=" * 70)
    print(f"Проверяем: {full_name}")

    result = find_employee_by_full_name(full_name)

    if result["status"] == "found":

        employee = result["employee"]

        print("СТАТУС: НАЙДЕН В БАЗЕ")
        print(f'ID: {employee["id"]}')
        print(f'ФИО: {employee["full_name"]}')
        print(f'Должность: {employee["position_name"]}')
        print(f'Телефон: {employee["phone"]}')
        print(f'Экипаж: {employee["crew_name"]}')

    else:

        print("СТАТУС: НЕ НАЙДЕН В БАЗЕ")


if __name__ == "__main__":

    # Реальный сотрудник из проверенного Word
    test_employee(
        "Ишутин Станислав Николаевич"
    )

    # Специально несуществующий сотрудник
    test_employee(
        "Тестовый Сотрудник Проверочный"
    )
