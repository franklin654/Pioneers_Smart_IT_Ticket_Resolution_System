export interface Coordinates {
  lat: number;
  lon: number;
}

export interface ForecastDay {
  day: string;
  temp: number;
  condition: string;
  neonTheme: string;
}

export interface WeatherData {
  city: string;
  country: string;
  temperature: number;
  feelsLike: number;
  condition: string;
  humidity: number;
  windSpeed: number;
  rainProbability: number;
  coordinates: Coordinates;
  neonTheme: string; // 'cyber-rain' | 'solar-flare' | 'neon-nebula' | 'grid-overcast' | 'cryo-snow' | 'plasma-storm'
  poeticDescription: string;
  forecast: ForecastDay[];
}

export type TempUnit = "C" | "F";
