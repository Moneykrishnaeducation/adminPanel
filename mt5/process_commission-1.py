from adminPanel.models import CommissionTransaction, TradingAccount, CustomUser

def process_commission_for_trade(trade):
    """
    Call this after a trade is closed to create a commission for the IB.
    `trade` should be an object or dict with at least:
      - client_email
      - trade_id
      - trading_account_id
      - symbol
      - position_type
      - position_direction
      - total_commission (the commission amount to split)
      - lot_size (optional, defaults to 1.0 if not provided)
    """
    import traceback
    try:
        client_user = CustomUser.objects.get(email=trade['client_email'])
        # Use select_related to fetch trading_account with group_name in single query
        trading_account = TradingAccount.objects.select_related('user').get(id=trade['trading_account_id'])
        total_commission = abs(trade['total_commission'])
        symbol = trade['symbol']
        position_type = trade.get('position_type', 'buy')
        position_direction = trade.get('position_direction', 'in')
        trade_id = trade['trade_id']
        lot_size = trade.get('lot_size', 1.0)  # Default to 1.0 lot if not provided

        # REMOVED: Redundant duplicate check - create_commission handles this internally with get_or_create
        # The duplicate check was causing double database queries and slowing down position detection

        # Override zero commission for specific symbols with fixed amounts
        # if total_commission == 0.0 and symbol in ['BTCUSD.r', 'ETHUSD.r']:
        #     total_commission = 10.0  # Set fixed commission amount
        #     print(f"DEBUG: Applied fixed commission for {symbol}: {total_commission}")

        # print(f"DEBUG: Processing commission for trade {trade_id} - Client: {trade['client_email']}, Symbol: {symbol}, Total Commission: {total_commission}, Lot Size: {lot_size}")

        # Pass lot_size, profit, deal_ticket, and mt5_close_time into the CommissionTransaction creator
        CommissionTransaction.create_commission(
            client=client_user,
            total_commission=total_commission,
            position_id=trade_id,
            trading_account=trading_account,
            trading_symbol=symbol,
            position_type=position_type,
            position_direction=position_direction,
            lot_size=lot_size,
            profit=float(trade.get('profit', 0.0)) if isinstance(trade, dict) else 0.0,
            deal_ticket=trade.get('deal_ticket'),  # MT5 Deal Ticket ID
            mt5_close_time=trade.get('mt5_close_time')  # MT5 close timestamp
        )
    except Exception as e:
        print(f'Failed to create commission for trade {trade}: {e}')
        traceback.print_exc()
        return False
