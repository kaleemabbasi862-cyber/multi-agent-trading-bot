using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using System.Globalization;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("Server URL", DefaultValue = "https://multi-agent-trading-bot.onrender.com")]
        public string ServerUrl { get; set; }

        [Parameter("Sync Interval (Sec)", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int SyncInterval { get; set; }

        [Parameter("Enable Auto Execution", DefaultValue = true)]
        public bool EnableAutoExecution { get; set; }

        [Parameter("Auto Break-Even Pips", DefaultValue = 15.0, MinValue = 5.0, MaxValue = 50.0)]
        public double AutoBreakEvenPips { get; set; }

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private readonly HashSet<string> _executedTickets = new HashSet<string>();

        protected override void OnStart()
        {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls;

            string assetName = "USD";
            try
            {
                if (Account.Asset != null && !string.IsNullOrEmpty(Account.Asset.Name))
                {
                    assetName = Account.Asset.Name;
                }
            }
            catch
            {
                assetName = "USD";
            }

            Print("=================================================");
            Print("TradeTalk.AI Autonomous Trading & Protection Bridge Started");
            Print("Account Number: " + Account.Number);
            Print("Live Balance: " + Account.Balance + " " + assetName);
            Print("Target Server: " + ServerUrl);
            Print("Sniper Auto Break-Even Guard: +" + AutoBreakEvenPips + " Pips");
            Print("=================================================");

            EnsureAllPositionsProtected();
            SendTelemetry();
            Timer.Start(SyncInterval);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Post-Execution & Open Trade Guard: Ensure every open position has valid SL and TP
                EnsureAllPositionsProtected();

                // 2. Dynamic Auto-Protection: Lock in profit to Break-Even at +15 Pips
                ApplyAutoBreakEvenProtection();

                // 3. Send live telemetry (Balance, Equity, Live Prices, Open Positions)
                SendTelemetry();

                // 4. Poll & Execute pending approved orders
                if (EnableAutoExecution)
                {
                    PollOrders();
                }
            }
            catch (Exception ex)
            {
                Print("Timer exception: " + ex.Message);
            }
        }

        /// <summary>
        /// Scans all open positions and attaches safe SL and TP if currently unprotected (-- / --).
        /// Specifically handles XAGUSD and XAUUSD minimum stop levels.
        /// </summary>
        private void EnsureAllPositionsProtected()
        {
            try
            {
                foreach (var pos in Positions)
                {
                    if (pos.StopLoss == null || pos.TakeProfit == null)
                    {
                        Symbol sym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                        int digits = sym.Digits;
                        double pipSize = sym.PipSize > 0 ? sym.PipSize : Math.Pow(10, -digits);
                        if (pos.SymbolName.Contains("XAG") || pos.SymbolName.Contains("SILVER"))
                        {
                            pipSize = Math.Pow(10, -digits);
                        }

                        double minDistance = Math.Max(pipSize * 25, Math.Max(sym.Spread * 2.5, (sym.StopLevel > 0 ? sym.StopLevel * pipSize * 2.0 : pipSize * 20)));

                        double? targetSl = pos.StopLoss;
                        double? targetTp = pos.TakeProfit;

                        if (pos.TradeType == TradeType.Buy)
                        {
                            if (targetSl == null) targetSl = Math.Round(pos.EntryPrice - Math.Max(minDistance, pipSize * 50), digits);
                            if (targetTp == null) targetTp = Math.Round(pos.EntryPrice + Math.Max(minDistance * 1.8, pipSize * 100), digits);
                        }
                        else
                        {
                            if (targetSl == null) targetSl = Math.Round(pos.EntryPrice + Math.Max(minDistance, pipSize * 50), digits);
                            if (targetTp == null) targetTp = Math.Round(pos.EntryPrice - Math.Max(minDistance * 1.8, pipSize * 100), digits);
                        }

                        Print(string.Format("🛡️ [Auto-Protection Guard] Securing position #{0} ({1} {2}): Setting SL={3}, TP={4}", 
                            pos.Id, pos.SymbolName, pos.TradeType, targetSl, targetTp));
                        
                        ModifyPosition(pos, targetSl, targetTp);
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Position protection guard note: " + ex.Message);
            }
        }

        private void ApplyAutoBreakEvenProtection()
        {
            try
            {
                foreach (var pos in Positions)
                {
                    if (pos.Pips >= AutoBreakEvenPips)
                    {
                        Symbol posSym = Symbols.GetSymbol(pos.SymbolName) ?? Symbol;
                        double pipSize = posSym.PipSize > 0 ? posSym.PipSize : Math.Pow(10, -posSym.Digits);

                        if (pos.TradeType == TradeType.Buy)
                        {
                            double targetBe = Math.Round(pos.EntryPrice + (1.0 * pipSize), posSym.Digits);
                            if (pos.StopLoss == null || pos.StopLoss < pos.EntryPrice)
                            {
                                Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} ({1} +{2:F1} Pips)! Moving SL to Break-Even @ {3:F5}", pos.Id, pos.SymbolName, pos.Pips, targetBe));
                                ModifyPosition(pos, targetBe, pos.TakeProfit);
                            }
                        }
                        else if (pos.TradeType == TradeType.Sell)
                        {
                            double targetBe = Math.Round(pos.EntryPrice - (1.0 * pipSize), posSym.Digits);
                            if (pos.StopLoss == null || pos.StopLoss > pos.EntryPrice)
                            {
                                Print(string.Format("🛡️ [Auto Break-Even] Locking Profit for #{0} ({1} +{2:F1} Pips)! Moving SL to Break-Even @ {3:F5}", pos.Id, pos.SymbolName, pos.Pips, targetBe));
                                ModifyPosition(pos, targetBe, pos.TakeProfit);
                            }
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Auto-BE note: " + ex.Message);
            }
        }

        private async void SendTelemetry()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/stream";
                string assetName = (Account.Asset != null && !string.IsNullOrEmpty(Account.Asset.Name)) ? Account.Asset.Name : "USD";
                string broker = Account.BrokerName ?? "IC Markets cTrader Live";

                string symClean = Symbol.Name.Replace("m", "").Replace(".pro", "").ToUpperInvariant();

                // Serialize Active Open Positions
                StringBuilder positionsJson = new StringBuilder("[");
                int count = 0;
                foreach (var pos in Positions)
                {
                    if (count > 0) positionsJson.Append(",");
                    
                    bool isBeActive = false;
                    if (pos.StopLoss != null)
                    {
                        if (pos.TradeType == TradeType.Buy && pos.StopLoss >= pos.EntryPrice) isBeActive = true;
                        if (pos.TradeType == TradeType.Sell && pos.StopLoss <= pos.EntryPrice) isBeActive = true;
                    }

                    positionsJson.Append(string.Format(
                        CultureInfo.InvariantCulture,
                        "{{\"id\":{0},\"symbol\":\"{1}\",\"trade_type\":\"{2}\",\"volume\":{3},\"entry_price\":{4},\"net_profit\":{5},\"pips\":{6},\"sl\":{7},\"tp\":{8},\"be_active\":{9}}}",
                        pos.Id,
                        pos.SymbolName,
                        pos.TradeType,
                        pos.VolumeInUnits,
                        pos.EntryPrice,
                        pos.NetProfit,
                        pos.Pips,
                        pos.StopLoss ?? 0,
                        pos.TakeProfit ?? 0,
                        isBeActive ? "true" : "false"
                    ));
                    count++;
                }
                positionsJson.Append("]");

                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"account_id\":\"{0}\",\"accountNumber\":\"{0}\",\"balance\":{1},\"equity\":{2},\"margin\":{3},\"freeMargin\":{4},\"currency\":\"{5}\",\"broker\":\"{6}\",\"symbol\":\"{7}\",\"bid\":{8},\"ask\":{9},\"live_price\":{8},\"open_positions\":{10}}}",
                    Account.Number,
                    Account.Balance,
                    Account.Equity,
                    Account.Margin,
                    Account.FreeMargin,
                    assetName,
                    broker,
                    symClean,
                    Symbol.Bid,
                    Symbol.Ask,
                    positionsJson.ToString()
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                var res = await httpClient.PostAsync(url, content);
                
                if (res.IsSuccessStatusCode && EnableAutoExecution)
                {
                    string replyJson = await res.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(replyJson) && (replyJson.Contains("\"pending_orders\"") || replyJson.Contains("\"ticket_id\"") || replyJson.Contains("\"signal\"")))
                    {
                        BeginInvokeOnMainThread(() => ProcessOrders(replyJson));
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Telemetry send note: " + ex.Message);
            }
        }

        private async void PollOrders()
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/orders";
                var response = await httpClient.GetAsync(url);
                if (response.IsSuccessStatusCode)
                {
                    string jsonResponse = await response.Content.ReadAsStringAsync();
                    if (!string.IsNullOrEmpty(jsonResponse) && jsonResponse != "[]")
                    {
                        if (jsonResponse.Contains("\"action\":\"CLOSE\""))
                        {
                            BeginInvokeOnMainThread(() => ProcessCloseCommand(jsonResponse));
                        }
                        else if (jsonResponse.Contains("symbol"))
                        {
                            BeginInvokeOnMainThread(() => ProcessOrders(jsonResponse));
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Order poll error: " + ex.Message);
            }
        }

        private void ProcessCloseCommand(string json)
        {
            try
            {
                long posId = 0;
                long.TryParse(ExtractJsonValue(json, "position_id"), NumberStyles.Any, CultureInfo.InvariantCulture, out posId);
                if (posId > 0)
                {
                    foreach (var pos in Positions)
                    {
                        if (pos.Id == posId)
                        {
                            Print("🚨 [TradeTalk Dashboard Command] Closing Position #" + posId + " with Net Profit: $" + pos.NetProfit);
                            ClosePosition(pos);
                            break;
                        }
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Close command error: " + ex.Message);
            }
        }

        private void ProcessOrders(string json)
        {
            try
            {
                string symbolStr = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "signal");
                if (string.IsNullOrEmpty(action)) action = ExtractJsonValue(json, "action");
                action = action.ToUpperInvariant();

                string signalId = ExtractJsonValue(json, "ticket_id");
                if (string.IsNullOrEmpty(signalId)) signalId = ExtractJsonValue(json, "id");

                if (string.IsNullOrEmpty(symbolStr) || string.IsNullOrEmpty(action) || (action != "BUY" && action != "SELL"))
                {
                    return;
                }

                if (!string.IsNullOrEmpty(signalId) && _executedTickets.Contains(signalId))
                {
                    return;
                }

                double lotSize = 0.01;
                double.TryParse(ExtractJsonValue(json, "lots"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) double.TryParse(ExtractJsonValue(json, "lot_size"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) lotSize = 0.01;

                double rawSl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawSl);

                double rawTp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out rawTp);

                Symbol targetSymbol = ResolveBrokerSymbol(symbolStr);
                if (targetSymbol == null)
                {
                    Print("❌ Error: Broker symbol not found for " + symbolStr);
                    return;
                }

                TradeType tradeType = (action == "BUY") ? TradeType.Buy : TradeType.Sell;

                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100000);
                if (targetSymbol.Name.Contains("XAU") || targetSymbol.Name.Contains("GOLD"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100);
                }
                else if (targetSymbol.Name.Contains("XAG") || targetSymbol.Name.Contains("SILVER"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 1000);
                }

                // 1. Commodity & Metal Precision Pip Size Normalization
                int digits = targetSymbol.Digits;
                double pipSize = targetSymbol.PipSize > 0 ? targetSymbol.PipSize : Math.Pow(10, -digits);
                if (targetSymbol.Name.Contains("XAG") || targetSymbol.Name.Contains("SILVER"))
                {
                    pipSize = Math.Pow(10, -digits);
                }

                // 2. Dynamic Stop-Level Enforcement (Minimum 2.5x Spread / StopLevel)
                double minDistance = Math.Max(pipSize * 25, Math.Max(targetSymbol.Spread * 2.5, (targetSymbol.StopLevel > 0 ? targetSymbol.StopLevel * pipSize * 2.0 : pipSize * 20)));

                double currentRefPrice = (tradeType == TradeType.Buy) ? targetSymbol.Ask : targetSymbol.Bid;
                double validSl = rawSl;
                double validTp = rawTp;

                if (tradeType == TradeType.Buy)
                {
                    if (validSl <= 0 || validSl >= (currentRefPrice - minDistance))
                    {
                        validSl = currentRefPrice - Math.Max(minDistance, pipSize * 50);
                    }
                    if (validTp <= 0 || validTp <= (currentRefPrice + minDistance))
                    {
                        validTp = currentRefPrice + Math.Max(minDistance * 1.8, pipSize * 100);
                    }
                }
                else
                {
                    if (validSl <= 0 || validSl <= (currentRefPrice + minDistance))
                    {
                        validSl = currentRefPrice + Math.Max(minDistance, pipSize * 50);
                    }
                    if (validTp <= 0 || validTp >= (currentRefPrice - minDistance))
                    {
                        validTp = currentRefPrice - Math.Max(minDistance * 1.8, pipSize * 100);
                    }
                }

                validSl = Math.Round(validSl, digits);
                validTp = Math.Round(validTp, digits);

                double slPips = Math.Round(Math.Abs(currentRefPrice - validSl) / pipSize, 1);
                double tpPips = Math.Round(Math.Abs(validTp - currentRefPrice) / pipSize, 1);

                Print(string.Format("🎯 [Dynamic Protection Execution] Dispatching {0} {1} ({2} Units | SL: {3} ({4} Pips) | TP: {5} ({6} Pips))...", 
                    action, targetSymbol.Name, volumeInUnits, validSl, slPips, validTp, tpPips));

                // 3. Attempt market execution with embedded SL/TP pips
                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI", slPips, tpPips);
                
                // 4. Auto-Recovery Fallback: If broker rejects embedded SL/TP, execute clean market order and modify immediately
                if (!result.IsSuccessful)
                {
                    Print("⚠️ Embedded SL/TP rejected by broker (" + result.Error + ") -> Instant clean Market Order fallback...");
                    result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI");
                }

                if (result.IsSuccessful && result.Position != null)
                {
                    Position pos = result.Position;
                    if (!string.IsNullOrEmpty(signalId)) _executedTickets.Add(signalId);

                    Print(string.Format("🟢 cTrader Order FILLED! Position ID: #{0} | Entry: {1} | Initial SL: {2} | Initial TP: {3}", 
                        pos.Id, pos.EntryPrice, pos.StopLoss, pos.TakeProfit));

                    // 5. Fallback Post-Execution Protection: Ensure SL and TP are 100% attached
                    if (pos.StopLoss == null || pos.TakeProfit == null)
                    {
                        try 
                        { 
                            Print(string.Format("🛡️ Attaching guaranteed protection to #{0}: SL={1}, TP={2}", pos.Id, validSl, validTp));
                            ModifyPosition(pos, validSl, validTp); 
                        } 
                        catch (Exception modEx)
                        {
                            Print("Secondary ModifyPosition note: " + modEx.Message);
                        }
                    }

                    // 6. Notify TradeTalk server with authentic cTrader Position ID
                    ReportOrderFilled(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
                }
                else
                {
                    Print("🔴 cTrader Execution Failed: " + result.Error);
                }
            }
            catch (Exception ex)
            {
                Print("MainThread Execution Exception: " + ex.Message);
            }
        }

        private Symbol ResolveBrokerSymbol(string symbolStr)
        {
            if (string.IsNullOrEmpty(symbolStr)) return Symbol;
            string clean = symbolStr.Replace("m", "").Replace(".pro", "").Replace("_i", "").Replace("/", "").ToUpperInvariant();

            return Symbols.GetSymbol(symbolStr)
                ?? Symbols.GetSymbol(clean)
                ?? Symbols.GetSymbol(clean + "m")
                ?? Symbols.GetSymbol(clean + ".pro")
                ?? Symbols.GetSymbol(clean + "_i")
                ?? Symbols.GetSymbol(clean + "micro")
                ?? Symbol;
        }

        private async void ReportOrderFilled(string signalId, long positionId, double fillPrice, string symbol, string action)
        {
            try
            {
                string url = ServerUrl.TrimEnd('/') + "/api/cbot/order-filled";
                string jsonPayload = string.Format(
                    CultureInfo.InvariantCulture,
                    "{{\"id\":\"{0}\",\"ticket_id\":\"CT_{1}\",\"position_id\":\"{1}\",\"fill_price\":{2},\"symbol\":\"{3}\",\"action\":\"{4}\",\"status\":\"FILLED\"}}",
                    signalId, positionId, fillPrice, symbol, action
                );

                var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");
                await httpClient.PostAsync(url, content);
            }
            catch
            {
            }
        }

        private string ExtractJsonValue(string json, string key)
        {
            string search = "\"" + key + "\":";
            int idx = json.IndexOf(search, StringComparison.OrdinalIgnoreCase);
            if (idx == -1) return "";
            int start = idx + search.Length;
            while (start < json.Length && (json[start] == ' ' || json[start] == '\"')) start++;
            int end = start;
            while (end < json.Length && json[end] != '\"' && json[end] != ',' && json[end] != '}') end++;
            return json.Substring(start, end - start).Trim('\"', ' ');
        }

        protected override void OnStop()
        {
            Print("TradeTalk Bridge Stopped.");
        }
    }
}
