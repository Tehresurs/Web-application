from app.repositories.crews import create_crew, get_all_crews


crew_id = create_crew(
    name="Экипаж №1",
    driver_full_name="Иванов Иван Иванович",
    driver_phone="+7 900 000-00-00",
    vehicle_make="Toyota Land Cruiser",
    vehicle_plate="А123АА86",
)

print("Создан экипаж ID:", crew_id)

print("\nЭкипажи:")

for crew in get_all_crews():
    print(crew)
