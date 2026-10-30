"""Dado sintético compartilhado entre a suíte de testes e o comando que popula o ambiente de navegador (R20)."""


def _digito_verificador(digitos):
    soma = sum(digito * peso for digito, peso in zip(digitos, range(len(digitos) + 1, 1, -1)))
    return soma * 10 % 11 % 10


def cpf_sintetico(sequencia):
    """CPF válido e determinístico para `sequencia` (inteiro ≥ 1); sequências distintas dão CPFs distintos até 10**9."""
    base = [int(letra) for letra in f'{sequencia * 987654321 % 10**9:09d}']
    base.append(_digito_verificador(base))
    base.append(_digito_verificador(base))
    return ''.join(map(str, base))

