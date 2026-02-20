# AI Trading Agent

class TradingAgent:
    def __init__(self, balance=10000):
        self.balance = balance
        self.position = 0

    def buy(self, price, quantity):
        cost = price * quantity
        if self.balance >= cost:
            self.position += quantity
            self.balance -= cost
            print(f'Bought {quantity} units at {price} each.')
        else:
            print('Not enough balance to buy.')

    def sell(self, price, quantity):
        if self.position >= quantity:
            revenue = price * quantity
            self.position -= quantity
            self.balance += revenue
            print(f'Sold {quantity} units at {price} each.')
        else:
            print('Not enough position to sell.')

    def current_status(self):
        return self.balance, self.position

# Example usage:
# agent = TradingAgent()
# agent.buy(100, 1)
# agent.sell(110, 1)
# print(agent.current_status())