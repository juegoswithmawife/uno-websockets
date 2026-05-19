import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
#import eventlet

# Configuración del servidor asíncrono no bloqueante
#eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secreto_uno_2026'
# Habilitamos CORS para evitar bloqueos de conexiones externas
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# --- MOTOR DE GENERACIÓN DEL MAZO ORIGINAL ---
def generar_mazo_uno():
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

# --- ESTADO GLOBAL EN MEMORIA RAM (Reemplaza a Google Sheets) ---
estado_juego = {
    "estado": "lobby",  # lobby o jugando
    "jugadores_listos": [],
    "turno_actual": 0,
    "direccion": 1,
    "carta_mesa": None,
    "color_activo": None,
    "acumulador": 0,
    "manos": {1: [], 2: [], 3: [], 4: []},
    "mazo": [],
    "alguien_con_uno": None,
    "ganador": None
}

@app.route('/')
def index():
    return render_template('juego.html')

# --- CONTROLADORES DE EVENTOS EN TIEMPO REAL ---

@socketio.on('conectarse')
def manejar_conexion():
    # Sincronización inmediata al abrir la pestaña
    emit('actualizacion_estado', estado_juego)

@socketio.on('unirse_jugador')
def unirse_jugador(data):
    jugador_id = int(data['jugador_id'])
    if jugador_id not in estado_juego["jugadores_listos"]:
        estado_juego["jugadores_listos"].append(jugador_id)
        estado_juego["jugadores_listos"].sort()
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('iniciar_partida')
def iniciar_partida():
    if not estado_juego["jugadores_listos"]:
        return
        
    mazo = generar_mazo_uno()
    
    # Reparto inicial de 7 cartas por jugador activo
    for p in estado_juego["jugadores_listos"]:
        estado_juego["manos"][p] = [mazo.pop() for _ in range(7)]
        
    # Extraer primera carta válida (no comodín)
    carta_inicio = mazo.pop()
    while 'W' in carta_inicio:
        mazo.insert(0, carta_inicio)
        carta_inicio = mazo.pop()
        
    estado_juego["mazo"] = mazo
    estado_juego["carta_mesa"] = carta_inicio
    estado_juego["color_activo"] = carta_inicio.split('_')[0]
    estado_juego["turno_actual"] = estado_juego["jugadores_listos"][0]
    estado_juego["direccion"] = 1
    estado_juego["acumulador"] = 0
    estado_juego["alguien_con_uno"] = None
    estado_juego["ganador"] = None
    estado_juego["estado"] = "jugando"
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('robar_carta')
def robar_carta(data):
    jugador_id = int(data['jugador_id'])
    if jugador_id != estado_juego["turno_actual"]:
        return
    
    acumulador = estado_juego["acumulador"]
    cantidad_a_robar = acumulador if acumulador > 0 else 1
    cartas_robadas = []
    
    for _ in range(cantidad_a_robar):
        # LÓGICA DE RECICLAJE DEL MAZO EN MEMORIA
        if not estado_juego["mazo"]:
            cartas_en_uso = set()
            for h in estado_juego["manos"].values():
                cartas_en_uso.update(h)
            cartas_en_uso.add(estado_juego["carta_mesa"])
            
            mazo_completo = generar_mazo_uno()
            estado_juego["mazo"] = [c for c in mazo_completo if c not in cartas_en_uso]
            random.shuffle(estado_juego["mazo"])
            
            if not estado_juego["mazo"]:
                break
                
        cartas_robadas.append(estado_juego["mazo"].pop())
        
    estado_juego["manos"][jugador_id].extend(cartas_robadas)
    
    # Verificar estado de UNO tras el robo
    actualizar_alertas_y_victoria()
    
    # Calcular transición de turno
    jugadores = estado_juego["jugadores_listos"]
    idx_actual = jugadores.index(jugador_id)
    sig_idx = (idx_actual + estado_juego["direccion"]) % len(jugadores)
    
    estado_juego["turno_actual"] = jugadores[sig_idx]
    estado_juego["acumulador"] = 0  # Castigo liquidado
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('jugar_carta')
def jugar_carta(data):
    jugador_id = int(data['jugador_id'])
    carta_id = data['carta_id']
    color_elegido = data.get('color_elegido', None)
    
    if jugador_id != estado_juego["turno_actual"]:
        return

    # Extracción de metadatos de las cartas
    c_color, c_valor, _ = carta_id.split('_')
    t_color, t_valor, _ = estado_juego["carta_mesa"].split('_')
    acumulador = estado_juego["acumulador"]
    color_activo = estado_juego["color_activo"]
    direccion = estado_juego["direccion"]
    jugadores = estado_juego["jugadores_listos"]

    # --- VALIDACIÓN DE REGLAS ORIGINALES ---
    if acumulador > 0:
        if c_valor != t_valor:
            msg = f"¡Penalización activa de +{acumulador}! Debes responder con un {t_valor} o robar."
            emit('error_juego', {"message": msg})
            return
    else:
        if c_color != 'W' and c_color != color_activo and c_valor != t_valor:
            emit('error_juego', {"message": "Jugada inválida. El color o el número no coinciden."})
            return

    # --- PROCESAMIENTO DE EFECTOS ---
    saltos = 1
    nuevo_color = c_color
    
    if c_valor == 'Rev':
        direccion *= -1
        estado_juego["direccion"] = direccion
        if len(jugadores) == 2:
            saltos = 2
    elif c_valor == 'Skip':
        saltos = 2
    elif c_valor == 'D2':
        acumulador += 2
    elif c_valor == 'D4':
        acumulador += 4
        nuevo_color = color_elegido
    elif c_color == 'W':
        nuevo_color = color_elegido

    # Consumo de la carta de la mano del jugador
    estado_juego["manos"][jugador_id].remove(carta_id)
    estado_juego["carta_mesa"] = carta_id
    estado_juego["color_activo"] = nuevo_color if c_color == 'W' else c_color
    estado_juego["acumulador"] = acumulador

    # Verificar si la jugada provoca un UNO o una victoria antes de pasar el turno
    actualizar_alertas_y_victoria()

    # Cálculo del índice del siguiente turno bajo efectos de saltos y direcciones
    idx_actual = jugadores.index(jugador_id)
    sig_idx = (idx_actual + (saltos * direccion)) % len(jugadores)
    estado_juego["turno_actual"] = jugadores[sig_idx]
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('pasar_turno')
def pasar_turno(data):
    jugador_id = int(data['jugador_id'])
    if jugador_id != estado_juego["turno_actual"] or estado_juego["acumulador"] > 0:
        return
        
    jugadores = estado_juego["jugadores_listos"]
    idx_actual = jugadores.index(jugador_id)
    sig_idx = (idx_actual + estado_juego["direccion"]) % len(jugadores)
    estado_juego["turno_actual"] = jugadores[sig_idx]
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

@socketio.on('reiniciar_juego')
def reiniciar_juego():
    # Volver al lobby vaciando la memoria RAM limpiamente
    estado_juego["estado"] = "lobby"
    estado_juego["jugadores_listos"] = []
    estado_juego["turno_actual"] = 0
    estado_juego["direccion"] = 1
    estado_juego["carta_mesa"] = None
    estado_juego["color_activo"] = None
    estado_juego["acumulador"] = 0
    estado_juego["manos"] = {1: [], 2: [], 3: [], 4: []}
    estado_juego["mazo"] = []
    estado_juego["alguien_con_uno"] = None
    estado_juego["ganador"] = None
    
    emit('actualizacion_estado', estado_juego, broadcast=True)

# --- FUNCIÓN AUXILIAR DE VERIFICACIÓN ---
def actualizar_alertas_y_victoria():
    estado_juego["alguien_con_uno"] = None
    for p in estado_juego["jugadores_listos"]:
        count = len(estado_juego["manos"][p])
        if count == 1:
            estado_juego["alguien_con_uno"] = p
        elif count == 0:
            estado_juego["ganador"] = p
            estado_juego["estado"] = "finalizado"

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)
