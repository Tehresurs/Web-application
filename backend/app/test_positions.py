from app.repositories.positions import (
    create_position,
    get_all_positions,
)


position_id = create_position(
    name="Инженер строительного контроля",
    action_description="Описание действий определим позже"
)

print("Создана должность ID:", position_id)

positions = get_all_positions()

print("\nДолжности:")
for position in positions:
    print(position)
