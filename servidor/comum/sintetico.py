"""Dado sintético compartilhado entre a suíte de testes e o comando que popula o ambiente de navegador (R20)."""


def _digito_verificador(digitos):
    soma = sum(digito * peso for digito, peso in zip(digitos, range(len(digitos) + 1, 1, -1)))
    return soma * 10 % 11 % 10


def cpf_sintetico(sequencia):
    """CPF válido e determinístico para `sequencia` (1 a 10**9 - 1); sequências distintas dão CPFs distintos.

    Dez sequências (0 e 999999919 a 999999991 de nove em nove) dariam onze dígitos iguais, que a validação do
    produto recusa: levantam `ValueError` em vez de devolver CPF inutilizável (Qodo e Greptile, PR #18).
    """
    if not 1 <= sequencia < 10**9:
        raise ValueError('sequencia fora de 1 a 10**9 - 1')
    base = [int(letra) for letra in f'{sequencia * 987654321 % 10**9:09d}']
    base.append(_digito_verificador(base))
    base.append(_digito_verificador(base))
    cpf = ''.join(map(str, base))
    if len(set(cpf)) == 1:
        raise ValueError('sequencia gera CPF de dígitos repetidos')
    return cpf

