using System;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using cAlgo.API;
using cAlgo.API.Internals;

namespace cAlgo.Robots
{
    [Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.FullAccess)]
    public class TradeTalkBridge : Robot
    {
        [Parameter("TradeTalk Server URL", DefaultValue = "https://multi-agent-trading-bot.onrender.com")]
        public string ServerUrl { get; set; }

        [Parameter("Poll Interval (Seconds)", DefaultValue = 2, MinValue = 1, MaxValue = 10)]
        public int PollIntervalSeconds { get; set; }

        [Parameter("Enable Auto Execution", DefaultValue = true)]
        public bool EnableAutoExecution { get; set; }

        protected override void OnStart()
        {
            // Set SecurityProtocol for HTTPS
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12 | SecurityProtocolType.Tls11 | SecurityProtocolType.Tls;

            Print("=================================================");
            Print("TradeTalk.AI Autonomous cBot Bridge Started");
            Print("Account ID: " + Account.Number);
            Print("Real Balance: " + Account.Balance + " " + Account.Currency);
            Print("Target API: " + ServerUrl);
            Print("=================================================");

            // Send initial registration heartbeat
            SendAccountHeartbeat();

            // Start timer for periodic heartbeat & order polling
            Timer.Start(PollIntervalSeconds);
        }

        protected override void OnTimer()
        {
            try
            {
                // 1. Send live account telemetry (Balance, Equity, Free Margin)
                SendAccountHeartbeat();

                // 2. Poll for approved AI trade signals to execute
                if (EnableAutoExecution)
                {
                    PollAndExecutePendingOrders();
                }
            }
            catch (Exception ex)
            {
                Print("TradeTalk Bridge Timer Exception: " + ex.Message);
            }
        }

        private void SendAccountHeartbeat()
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/heartbeat";
                
                // Build JSON payload
                string jsonPayload = string.Format(
                    "{{\"account_id\":\"{0}\",\"balance\":{1},\"equity\":{2},\"margin\":{3},\"free_margin\":{4},\"currency\":\"{5}\",\"broker\":\"{6}\"}}",
                    Account.Number,
                    Account.Balance.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    Account.Equity.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    Account.Margin.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    Account.FreeMargin.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    Account.Currency,
                    Account.BrokerName ?? "cTrader Live"
                );

                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(endpoint);
                request.Method = "POST";
                request.ContentType = "application/json";
                request.Timeout = 4000;

                byte[] byteArray = Encoding.UTF8.GetBytes(jsonPayload);
                request.ContentLength = byteArray.Length;

                using (Stream dataStream = request.GetRequestStream())
                {
                    dataStream.Write(byteArray, 0, byteArray.Length);
                }

                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                {
                    // Success
                }
            }
            catch (Exception ex)
            {
                // Non-blocking log
                Print("Heartbeat dispatch: " + ex.Message);
            }
        }

        private void PollAndExecutePendingOrders()
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/orders";
                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(endpoint);
                request.Method = "GET";
                request.Accept = "application/json";
                request.Timeout = 4000;

                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
                using (Stream stream = response.GetResponseStream())
                using (StreamReader reader = new StreamReader(stream))
                {
                    string jsonResponse = reader.ReadToEnd();
                    if (!string.IsNullOrEmpty(jsonResponse) && jsonResponse != "[]" && jsonResponse.Contains("symbol"))
                    {
                        ProcessOrdersJson(jsonResponse);
                    }
                }
            }
            catch (Exception ex)
            {
                Print("Order Poll note: " + ex.Message);
            }
        }

        private void ProcessOrdersJson(string json)
        {
            try
            {
                Print("[TradeTalk Signal Received]: " + json);

                // Simple JSON parser for cBot execution
                string symbol = ExtractJsonValue(json, "symbol");
                string action = ExtractJsonValue(json, "action").ToUpper();
                string id = ExtractJsonValue(json, "id");
                
                double lotSize = 0.01;
                double.TryParse(ExtractJsonValue(json, "lot_size"), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out lotSize);
                if (lotSize <= 0) lotSize = 0.01;

                double sl = 0;
                double.TryParse(ExtractJsonValue(json, "sl"), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out sl);

                double tp = 0;
                double.TryParse(ExtractJsonValue(json, "tp"), System.Globalization.NumberStyles.Any, System.Globalization.CultureInfo.InvariantCulture, out tp);

                // Resolve Symbol on cTrader
                Symbol targetSymbol = Symbols.GetSymbol(symbol) ?? Symbols.GetSymbol(symbol + "m") ?? Symbol;
                TradeType tradeType = action == "BUY" ? TradeType.Buy : TradeType.Sell;

                // Normalize Volume to cTrader Symbol Units
                double volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100000);
                if (targetSymbol.Name.Contains("XAU") || targetSymbol.Name.Contains("GOLD"))
                {
                    volumeInUnits = targetSymbol.NormalizeVolumeInUnits(lotSize * 100);
                }

                Print(string.Format("Executing {0} {1} Units of {2} | SL: {3}, TP: {4}", tradeType, volumeInUnits, targetSymbol.Name, sl, tp));

                var result = ExecuteMarketOrder(tradeType, targetSymbol.Name, volumeInUnits, "TradeTalk.AI", null, null);
                if (result.IsSuccessful && result.Position != null)
                {
                    Print("🟢 Trade Executed! Position ID: " + result.Position.Id + " @ " + result.Position.EntryPrice);
                    
                    // Modify SL and TP on the live position
                    if (sl > 0 || tp > 0)
                    {
                        ModifyPosition(result.Position, sl > 0 ? (double?)sl : null, tp > 0 ? (double?)tp : null);
                    }

                    // Report confirmation back to TradeTalk API
                    ReportExecutionConfirmation(id, result.Position.Id, result.Position.EntryPrice, targetSymbol.Name, action);
                }
                else
                {
                    Print("❌ Order execution failed: " + result.Error);
                }
            }
            catch (Exception ex)
            {
                Print("Error processing order: " + ex.Message);
            }
        }

        private void ReportExecutionConfirmation(string signalId, long positionId, double fillPrice, string symbol, string action)
        {
            try
            {
                string endpoint = ServerUrl.TrimEnd('/') + "/api/cbot/order-filled";
                string jsonPayload = string.Format(
                    "{{\"id\":\"{0}\",\"ticket_id\":\"CT_{1}\",\"position_id\":\"{1}\",\"fill_price\":{2},\"symbol\":\"{3}\",\"action\":\"{4}\",\"status\":\"FILLED\"}}",
                    signalId, positionId, fillPrice.ToString(System.Globalization.CultureInfo.InvariantCulture), symbol, action
                );

                HttpWebRequest request = (HttpWebRequest)WebRequest.Create(endpoint);
                request.Method = "POST";
                request.ContentType = "application/json";
                byte[] byteArray = Encoding.UTF8.GetBytes(jsonPayload);
                request.ContentLength = byteArray.Length;

                using (Stream dataStream = request.GetRequestStream())
                {
                    dataStream.Write(byteArray, 0, byteArray.Length);
                }

                using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) { }
            }
            catch (Exception ex)
            {
                Print("Report confirmation note: " + ex.Message);
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
