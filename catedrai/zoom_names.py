"""A small local first-name/last-name pool for generating a plausible display
name each time the bot joins a meeting - so it shows up as an ordinary
participant instead of a fixed, obviously-automated name."""

from __future__ import annotations

import random

FIRST_NAMES = [
    "Santiago", "Mariana", "Andrés", "Camila", "Juan", "Valentina", "Carlos",
    "Isabella", "Daniel", "Sofía", "Miguel", "Valeria", "Alejandro", "Daniela",
    "Sebastián", "Gabriela", "David", "Laura", "Diego", "Paula", "Felipe",
    "Natalia", "Nicolás", "Manuela", "Samuel", "Juliana", "Martín", "Luisa",
    "Emiliano", "Antonia",
]

LAST_NAMES = [
    "García", "Rodríguez", "Martínez", "López", "González", "Pérez",
    "Sánchez", "Ramírez", "Torres", "Flórez", "Rivera", "Gómez", "Díaz",
    "Vargas", "Castro", "Ortiz", "Morales", "Suárez", "Rojas", "Herrera",
    "Jiménez", "Ruiz", "Álvarez", "Romero", "Moreno", "Muñoz", "Restrepo",
    "Cárdenas", "Salazar", "Mejía",
]


def random_display_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
