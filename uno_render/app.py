from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import random
import eventlet

# Configuración del servidor asíncrono
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secreto_uno_2026'
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# --- LÓGICA DEL MAZO ---
def generar_mazo():
    colores = ['R', 'B', 'G', 'Y']
    acciones = ['Skip', 'Rev', 'D2']
    mazo = []
    for color in colores:
        mazo.append(f"{color}_0_1")
        for n in range(1, 10):
            mazo.extend([f"{color}_{n}_1", f"{color}_{n}_2"])
        for a in acciones:
            mazo.extend([f"{color}_{a}_1", f"{color}_{a}_2"])
    for i in range(1, 5):
        mazo.extend([f"W_Color_{i}", f"W_D4_{i}"])
    random.shuffle(mazo)
    return mazo

# --- ESTADO GLOBAL EN RAM ---
estado_juego = {
    "estado": "lobby", # lobby o jugando
    "jugadores_listos": [],
    "turno_actual": 0,
    "sentido": 1,
    "carta_mesa": None,
    "color_activo": None,
    "acumulador": 0,
    "manos": {1: [], 2: [], 3: [], 4: []},
    "mazo": []
}

@app.route('/')
def index():
    return render_template('juego.html')

# --- EVENTOS DE WEBSOCKETS (TIEMPO REAL) ---

@socketio.on('conectarse')
def manejar_conexion():
    # Cuando alguien entra a la web, le enviamos el estado actual al instante
    emit('actualizacion_estado', estado_juego)

@socketio.on('unirse_jugador')
def unirse_jugador(data):
    jugador_id = data['jugador_id']
    if jugador_id not in estado_juego["jugadores_listos"]:
        estado_juego["jugadores_listos"].append(jugador_id)
        estado_juego["jugadores_listos"].sort()
    # Avisamos a TODOS de que alguien se ha unido
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('iniciar_partida')
def iniciar_partida():
    if len(estado_juego["jugadores_listos"]) == 0:
        return
        
    mazo = generar_mazo()
    for p in estado_juego["jugadores_listos"]:
        estado_juego["manos"][p] = [mazo.pop() for _ in range(7)]
        
    primera_carta = mazo.pop()
    while primera_carta.startswith('W'):
        mazo.insert(0, primera_carta)
        primera_carta = mazo.pop()
        
    estado_juego["mazo"] = mazo
    estado_juego["carta_mesa"] = primera_carta
    estado_juego["color_activo"] = primera_carta.split('_')[0]
    estado_juego["turno_actual"] = estado_juego["jugadores_listos"][0]
    estado_juego["estado"] = "jugando"
    estado_juego["acumulador"] = 0
    estado_juego["sentido"] = 1
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('robar_carta')
def robar_carta(data):
    jugador_id = data['jugador_id']
    if jugador_id != estado_juego["turno_actual"]: return
    
    cantidad = estado_juego["acumulador"] if estado_juego["acumulador"] > 0 else 1
    
    for _ in range(cantidad):
        if not estado_juego["mazo"]:
            # Si se acaba, generamos uno nuevo rápido (sin las de las manos)
            estado_juego["mazo"] = generar_mazo() 
        estado_juego["manos"][jugador_id].append(estado_juego["mazo"].pop())
        
    # Calcular siguiente turno
    idx_actual = estado_juego["jugadores_listos"].index(jugador_id)
    sig_idx = (idx_actual + estado_juego["sentido"]) % len(estado_juego["jugadores_listos"])
    
    estado_juego["turno_actual"] = estado_juego["jugadores_listos"][sig_idx]
    estado_juego["acumulador"] = 0
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('jugar_carta')
def jugar_carta(data):
    jugador_id = data['jugador_id']
    carta_id = data['carta_id']
    color_elegido = data.get('color_elegido')
    
    if jugador_id != estado_juego["turno_actual"]: return
    
    # --- Aquí iría la lógica de validación de saltos y castigos ---
    # Para mantener este paso a paso claro, aplicamos el cambio básico:
    c_color, c_valor, _ = carta_id.split('_')
    
    estado_juego["manos"][jugador_id].remove(carta_id)
    estado_juego["carta_mesa"] = carta_id
    estado_juego["color_activo"] = color_elegido if c_color == 'W' else c_color
    
    # Calcular siguiente turno
    idx_actual = estado_juego["jugadores_listos"].index(jugador_id)
    sig_idx = (idx_actual + estado_juego["sentido"]) % len(estado_juego["jugadores_listos"])
    estado_juego["turno_actual"] = estado_juego["jugadores_listos"][sig_idx]
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('reiniciar_juego')
def reiniciar_juego():
    estado_juego["estado"] = "lobby"
    estado_juego["jugadores_listos"] = []
    estado_juego["manos"] = {1: [], 2: [], 3: [], 4: []}
    emit('actualizacion_estado', estado_juego, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)