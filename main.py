import json
import logging
import time
import random
from web3 import Web3
from eth_account import Account

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NetworkSlug:
    ARBITRUM_ONE = "arbitrum_one"
    OPTIMISM = "optimism"

SEPOLIA_ETH_TOKEN = '0xE71bDfE1Df69284f00EE185cf0d95d0c7680c0d4'
QUOTER_ADDRESS = '0xb27308f9f90d607463bb33ea1bebb41c27ce5ab6'

CONTRACT_ADDRESS = {
    NetworkSlug.ARBITRUM_ONE: "0xfcA99F4B5186D4bfBDbd2C542dcA2ecA4906BA45",
    NetworkSlug.OPTIMISM: "0x8352C746839699B1fc631fddc0C3a00d4AC71A17",
}

ADDRESS_ZERO = "0x0000000000000000000000000000000000000000"
SEPOLIA_CHAIN_ID = 161


WETH_ADDRESS_BY_NETWORK = {
    NetworkSlug.ARBITRUM_ONE: "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
    NetworkSlug.OPTIMISM: "0x4200000000000000000000000000000000000006"
}

RPC_URLS = {
    NetworkSlug.ARBITRUM_ONE: "https://arb1.arbitrum.io/rpc",
    NetworkSlug.OPTIMISM: "https://rpc.ankr.com/optimism"
}

try:
    with open("abi.json", "r") as abi_file:
        BRIDGE_ABI = json.load(abi_file)
except FileNotFoundError:
    logger.error("Файл abi.json не найден.")
    exit(1)
except json.JSONDecodeError:
    logger.error("Ошибка при чтении файла abi.json.")
    exit(1)

def load_private_keys(file_path="keys.txt"):
    try:
        with open(file_path, "r") as file:
            keys = [line.strip() for line in file if line.strip()]
            return keys
    except FileNotFoundError:
        logger.error(f"Файл {file_path} не найден.")
        exit(1)

def process_account(private_key, network_slug, amount_in_ether, slippage):
    rpc_url = RPC_URLS[network_slug]
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    if not web3.is_connected():
        logger.error(f"Не удалось подключиться к RPC для сети {network_slug}.")
        return

    account = Account.from_key(private_key)
    from_address = account.address
    logger.info(f"Обработка аккаунта: {from_address}")

    if network_slug not in CONTRACT_ADDRESS or network_slug not in RPC_URLS:
        logger.error(f"Сеть {network_slug} не поддерживается.")
        return

    bridge_contract_address = Web3.to_checksum_address(CONTRACT_ADDRESS[network_slug])
    bridge_contract = web3.eth.contract(address=bridge_contract_address, abi=BRIDGE_ABI)
    uniswap_quoter_contract = web3.eth.contract(address=Web3.to_checksum_address(QUOTER_ADDRESS), abi=BRIDGE_ABI)
    estimate_send_fee_contract = web3.eth.contract(address=Web3.to_checksum_address(SEPOLIA_ETH_TOKEN), abi=BRIDGE_ABI)

    weth_token_address = Web3.to_checksum_address(WETH_ADDRESS_BY_NETWORK[network_slug])
    amount_wei = Web3.to_wei(amount_in_ether, "ether")

    try:
        send_fee = estimate_send_fee_contract.functions.estimateSendFee(
            SEPOLIA_CHAIN_ID,
            Web3.to_bytes(hexstr=f'0x{str(1).zfill(64)}'),
            amount_wei,
            False,
            Web3.to_bytes(hexstr='0x')
        ).call()

        amount_out = uniswap_quoter_contract.functions.quoteExactInputSingle(
            weth_token_address,
            Web3.to_checksum_address(SEPOLIA_ETH_TOKEN),
            3000,
            amount_wei,
            0
        ).call()

        min_amount_out = int(amount_out * slippage)

        if network_slug == NetworkSlug.ARBITRUM_ONE:
            to_address = from_address
            refund_address = from_address
        else:
            to_address = from_address
            refund_address = from_address

        latest_block = web3.eth.get_block('latest')
        base_fee = latest_block['baseFeePerGas']
        max_priority_fee_per_gas = web3.to_wei(1, 'gwei')  # Приоритетная плата (можно настроить)
        max_fee_per_gas = base_fee + max_priority_fee_per_gas
        logger.info(
            f"baseFee: {base_fee}, maxPriorityFeePerGas: {max_priority_fee_per_gas}, maxFeePerGas: {max_fee_per_gas}")

        tx = bridge_contract.functions.swapAndBridge(
            amount_wei,
            min_amount_out,
            SEPOLIA_CHAIN_ID,
            to_address,
            refund_address,
            ADDRESS_ZERO,
            b""
        ).build_transaction({
            'from': from_address,
            'value': amount_wei + send_fee[0],
            'gas': 700000,
            'maxFeePerGas': max_fee_per_gas,
            'maxPriorityFeePerGas': max_priority_fee_per_gas,
            'nonce': web3.eth.get_transaction_count(from_address)
        })

        signed_tx = web3.eth.account.sign_transaction(tx, private_key)
        tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
        logger.info(f"Транзакция отправлена: {web3.to_hex(tx_hash)}")

        receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status == 1:
            logger.info(f"Транзакция подтверждена: {web3.to_hex(tx_hash)}")
        else:
            logger.error("Транзакция не была успешной.")
    except Exception as e:
        logger.error(f"Ошибка обработки аккаунта {from_address}: {str(e)}")

def main():
    private_keys = load_private_keys()
    print("Выберите сеть:")
    print("1 - Arbitrum One")
    print("2 - Optimism")
    network_choice = input("Введите номер сети: ").strip()

    if network_choice == "1":
        network_slug = NetworkSlug.ARBITRUM_ONE
    elif network_choice == "2":
        network_slug = NetworkSlug.OPTIMISM
    else:
        logger.error("Неверный выбор сети.")
        return

    amount_min = float(input("Введите минимальное количество ETH для бриджа: ").strip())
    amount_max = float(input("Введите максимальное количество ETH для бриджа: ").strip())
    slippage_str = input("Введите слиппедж (например 0.1 для 10%): ").strip()
    delay_min = int(input("Введите минимальную задержку между аккаунтами (в секундах): ").strip())
    delay_max = int(input("Введите максимальную задержку между аккаунтами (в секундах): ").strip())

    slippage = float(slippage_str)

    for private_key in private_keys:
        amount_in_ether = random.uniform(amount_min, amount_max)
        logger.info(f"Выбрана сумма для аккаунта: {amount_in_ether:.6f} ETH")
        process_account(private_key, network_slug, amount_in_ether, slippage)
        delay = random.randint(delay_min, delay_max)
        logger.info(f"Ожидание {delay} секунд перед обработкой следующего аккаунта.")
        time.sleep(delay)

if __name__ == "__main__":
    main()
