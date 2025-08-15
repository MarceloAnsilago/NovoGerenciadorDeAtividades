# utils.py
import random
import string

def gerar_senha_provisoria(tamanho=10):
    caracteres = string.ascii_letters + string.digits
    return ''.join(random.choice(caracteres) for _ in range(tamanho))