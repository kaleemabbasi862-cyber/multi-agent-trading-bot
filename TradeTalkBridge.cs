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

        [Parameter("Enable AI Break-Even Protection", DefaultValue = false)]
        public bool EnableBreakEven { get; set; }

        [Parameter("Enable Smart Trailing Stop", DefaultValue = false)]
        public bool EnableTrailingStop { get; set; }

        private static readonly HttpClient httpClient = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        private readonly HashSet<long> _ignoredPositions = new HashSet<long>();

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
            Print("TradeTalk.AI Autonomous cBot Bridge Started");
            Print("Account Number: " + Account.Number);
            Print("Live Balance: " + Account.Balance + " " + assetName);
            Print("Target Server: " + ServerUrl);
            Print("=================================================");

            // Send initial registration packet
            SendTelemetry();

            // Continuous background timer
            Timer.Start(SyncInterval);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Send live telemetry (Balance, Equity, Live Prices, Open Positions)
                SendTelemetry();

                // 2. Poll & Execute pending approved orders / AI management commands
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

                // Ensure culture-invariant float format
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
                await httpClient.PostAsync(url, content);
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
                            // Process manual close command from dashboard
                            ProcessCloseCommand(jsonResponse);
                        }
                        else if (jsonResponse.Contains("symbol"))
                        {
                            ProcessOrders(jsonResponse);
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
                Print("[TradeTalk Signal Received]: " + json);

                string symbol = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "action").ToUpperInvariant();
                string signalId = ExtractJsonValue(json, "id");

                double lotSize = 0.01;
                double.TryParse(ExtractJsonValue(json, "lot_size"), NumberStyles.Any, CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) lotSize = 0.01;

                double sl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), NumberStyles.Any, CultureInfo.InvariantCulture, out sl);

                double tp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), NumberStyles.Any, CultureInfo.InvariantCulture, out tp);

                Symbol targetSymbol = Symbols.GetSymbol(symbol) ?? Symbols.GetSymbol(symbol + "m") ?? Symbol;
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

                TradeResult result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI");
                if (result.IsSuccessful && result.Position != null)
                {
                    Position pos = result.Position;
                    Print("🟢 cTrader Order Executed! Position ID: " + pos.Id + " @ " + pos.EntryPrice);

                    if (sl > 0 || tp > 0)
                    {
                        double? slPrice = sl > 0 ? (double?)sl : null;
                        double? tpPrice = tp > 0 ? (double?)tp : null;
                        ModifyPosition(pos, slPrice, tpPrice, ProtectionType.Absolute);
                    }

                    ReportOrderFilled(signalId, pos.Id, pos.EntryPrice, targetSymbol.Name, action);
                }
            }
            catch (Exception ex)
            {
                Print("Execution Error: " + ex.Message);
            }
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
